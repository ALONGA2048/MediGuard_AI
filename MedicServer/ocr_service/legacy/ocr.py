"""自動辨識 test 資料夾內的所有照片，不使用攝影機或資料庫。

使用方式：
    1. 在本程式旁建立 test 資料夾。
    2. 將照片放入 test 資料夾或其子資料夾。
    3. 執行：python ocr_photo_only.py

程式只載入一次模型，逐張辨識後輸出文字與信心度，不輸出座標。
實際送入 OCR 的轉正影像會儲存在 ocr_processed 資料夾。
"""

import argparse
import csv
import json
import difflib
import math
import os
import re
import sys
import time
import ctypes
from ocr_diagnostics import span, record_exception, exception_details
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np
import zxingcpp

# oneDNN/MKL-DNN can retain detector primitives for every input shape during a
# long Windows CPU batch.  Hundreds of differently sized package ROIs may then
# fail with "could not create a primitive".  PaddleOCR still uses its normal
# CPU predictor when this is disabled.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
from paddleocr import PaddleOCR


# ============================================================
# OCR 設定
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
TEST_DIR = BASE_DIR / "test"
PROCESSED_DIR = BASE_DIR / "ocr_processed"
DEFAULT_VAL_DIR = BASE_DIR.parent / "yolo_classification" / "dataset" / "test"
DEFAULT_REPORT_DIR = BASE_DIR / "ocr_reports"
DEFAULT_BARCODE_DEBUG_DIR = BASE_DIR / "barcode_debug"
DRUG_REVIEW_FILENAME = "generated_drugs_review.csv"
DRUG_SQL_FILENAME = "generated_drugs.sql"
PAIR_PATTERN = re.compile(r"^(\d{6})_cam([01])$", re.IGNORECASE)
BATCH_MIN_CONFIDENCE = 0.80

# 核對英文資料夾名稱時不採用這些沒有辨識力的通用字。
GENERIC_ENGLISH_WORDS = {
    "tablet", "tablets", "tab", "capsule", "capsules", "cap", "film",
    "coated", "extended", "release", "effervescent", "granules", "fc",
    "sc", "mg", "hcl", "hydrochloride", "anhydrous",
}

IMAGE_EXTENSIONS = {
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

OCR_DET_LIMIT_SIDE_LEN = 2560
OCR_ENGINE_DROP_SCORE = 0.20
OCR_OUTPUT_MIN_CONFIDENCE = 0.45
OCR_USE_GPU = os.getenv("PADDLE_OCR_USE_GPU", "0").strip() == "1"
OCR_ENABLE_MKLDNN = False
OCR_CPU_THREADS = max(1, min(4, os.cpu_count() or 1))

# 640x480 的文字太小，先把長邊放大到約 1920；高解析圖片不再額外放大。
OCR_TARGET_LONG_SIDE = 1920
OCR_MAX_UPSCALE = 3.0
OCR_UPSCALE = 2.5
OCR_PACKAGE_PADDING_X = 0.40
OCR_PACKAGE_PADDING_Y = 0.35
OCR_MIN_EDGE_MARGIN_RATIO = 0.08
OCR_DESKEW_MIN_ANGLE = 1.0
OCR_DESKEW_MAX_ANGLE = 45.0
OCR_CLUSTER_DISTANCE_RATIO = 0.045
OCR_CLUSTER_ANGLE_TOLERANCE = 12.0
ORIENTATION_MIN_SCORE_MARGIN = 0.15
ORIENTATION_MIN_WIDTH = 80
ORIENTATION_MIN_HEIGHT = 60
ORIENTATION_MIN_AVERAGE_CONFIDENCE = 0.45
# A larger number of low-confidence fragments must not beat a smaller set of
# consistently reliable text.  Treat 0.20 as an absolute confidence gap
# (20 percentage points), and require the alternative direction to have at
# least as much total confidence as the score winner before overriding it.
ORIENTATION_CONFIDENCE_AVERAGE_OVERRIDE_GAP = 0.20
OCR_ORIENTATION_DEBUG = os.getenv("OCR_ORIENTATION_DEBUG", "1").strip() == "1"
USE_AI_SUPER_RESOLUTION = False

# Expensive angle search is a database-failure fallback, not the normal OCR
# path. The zero-degree ROI candidate is retained so cropping/upscaling can
# help without forcing a rotation. Negative values are clockwise in OpenCV.
# The normal OCR pass already covers the unrotated image (and its 180-degree
# counterpart).  Keeping 0 here repeated the exact same direction during the
# expensive fallback sweep.
ANGLE_FALLBACK_ANGLES = (-45, -60, -75, 45, 60, 75, -90, 90)
ANGLE_FALLBACK_TOP_ENGLISH = 3
ANGLE_FALLBACK_MIN_SCORE_GAIN = 3.0
ANGLE_FALLBACK_MIN_VALID_CHAR_GAIN = 4
ANGLE_FALLBACK_MAX_AVERAGE_CONFIDENCE_DROP = 0.05

BARCODE_PADDING_X = 0.15
BARCODE_PADDING_Y = 0.25
BARCODE_LOW_RESOLUTION_WIDTH = 120
BARCODE_MAX_CANDIDATES = 6
BARCODE_MIN_ASPECT_RATIO = 2.0
BARCODE_MIN_STRIPE_COUNT = 8
BARCODE_MIN_STRIPE_DENSITY = 0.035
BARCODE_MIN_STRIPE_HEIGHT_RATIO = 0.45
BARCODE_MAX_STRIPE_HEIGHT_MAD = 0.22
BARCODE_MIN_XY_GRADIENT_RATIO = 1.35
BARCODE_MIN_VERTICAL_CONTINUITY = 0.50
BARCODE_MAX_ASPECT_RATIO = 8.0
BARCODE_LARGE_HEIGHT_RATIO = 0.32
BARCODE_LARGE_AREA_RATIO = 0.22
BARCODE_ROW_DENSITY_RATIO = 0.28
BARCODE_COLUMN_DENSITY_RATIO = 0.28
BARCODE_PROFILE_MAX_GAP_RATIO = 0.025

DRUG_REVIEW_FIELDS = [
    "folder_name", "drug_name_en", "drug_name_zh", "ingredient_en",
    "ingredient_zh", "strength", "dosage_form_en", "dosage_form_zh", "license_number",
    "barcode", "manufacturer", "drug_name_en_evidence",
    "drug_name_zh_evidence", "ingredient_en_evidence",
    "ingredient_zh_evidence", "strength_evidence",
    "license_number_evidence", "barcode_evidence",
    "manufacturer_evidence", "warning",
]
DRUG_REVIEW_EDITABLE_FIELDS = {
    "drug_name_en", "drug_name_zh", "ingredient_en", "ingredient_zh",
    "strength", "dosage_form_en", "dosage_form_zh", "license_number", "barcode", "manufacturer",
}
DRUG_REVIEW_EVIDENCE_FIELDS = {
    field for field in DRUG_REVIEW_FIELDS if field.endswith("_evidence")
}
DRUG_REVIEW_EMPTY_VALUE = "待人工確認"
DRUG_REVIEW_FIELD_PROMPTS = {
    "drug_name_en": "待填英文藥名",
    "drug_name_zh": "待填中文藥名",
    "ingredient_en": "待填英文成分",
    "ingredient_zh": "待填中文成分",
    "strength": "待填劑量或規格",
    "dosage_form_en": "待填英文劑型",
    "dosage_form_zh": "待填中文劑型",
    "license_number": "待填許可證號",
    "barcode": "待填條碼",
    "manufacturer": "待填製造商",
}
DRUG_REVIEW_NO_EVIDENCE = "無OCR證據"
DRUG_REVIEW_NO_WARNING = "無"

DOSAGE_FORMS = [
    "F.C. Tablets", "F.C. Tablet", "S.C. Tablets", "S.C. Tablet",
    "Effervescent Tablets", "Effervescent Tablet",
    "Chewable Tablets", "Chewable Tablet",
    "Film-Coated Tablet", "Extended Release Tablet",
    "S.C. Tab", "F.C. Tab", "Granules", "Tablets", "Tablet",
    "Capsules", "Capsule", "Tabs", "Tab", "Caps", "Cap",
]

DOSAGE_FORM_ZH = {
    "tablet": "錠劑", "tablets": "錠劑", "tab": "錠劑", "tabs": "錠劑",
    "capsule": "膠囊", "capsules": "膠囊", "cap": "膠囊", "caps": "膠囊",
    "granules": "顆粒劑",
    "effervescent tablet": "發泡錠", "effervescent tablets": "發泡錠",
    "chewable tablet": "咀嚼錠", "chewable tablets": "咀嚼錠",
    "f.c. tab": "膜衣錠", "f.c. tablet": "膜衣錠", "f.c. tablets": "膜衣錠",
    "s.c. tab": "糖衣錠", "s.c. tablet": "糖衣錠", "s.c. tablets": "糖衣錠",
    "film-coated tablet": "膜衣錠",
    "extended release tablet": "緩釋錠",
}

# PP-OCRv4 的中文模型。實測 chinese_cht 舊模型會把這批小字幾乎全判成
# 拉丁字母；新版 ch 模型雖以簡體字形為主，對繁體中文仍能正確偵測與辨識。
TRADITIONAL_LANGUAGE = "ch"
TRADITIONAL_OCR_VERSION = "PP-OCRv4"

# 額外跑英文模型，加強英文藥名與數字辨識。
RUN_EXTRA_ENGLISH_PASS = True
ENGLISH_LANGUAGE = "en"
ENGLISH_OCR_VERSION = "PP-OCRv4"

def to_traditional_chinese(text: str) -> str:
    """使用 Windows NLS 將 OCR 文字統一轉成繁體中文（台灣字集）。

    PP-OCRv4 的 ``ch`` 模型對照片中的中文小字辨識較好，但模型可能輸出
    簡體字。品名比對、證據與畫面輸出前一律經過此函式，避免把「爱、锭」
    等簡體字顯示或保存為最終結果。
    """
    if not text or os.name != "nt":
        return text

    lcmap_string_ex = ctypes.windll.kernel32.LCMapStringEx
    traditional_chinese = 0x04000000  # LCMAP_TRADITIONAL_CHINESE
    required = lcmap_string_ex(
        "zh-TW", traditional_chinese, text, len(text), None, 0, None, None, 0
    )
    if required <= 0:
        return text

    buffer = ctypes.create_unicode_buffer(required)
    converted = lcmap_string_ex(
        "zh-TW",
        traditional_chinese,
        text,
        len(text),
        buffer,
        required,
        None,
        None,
        0,
    )
    return buffer.value if converted > 0 else text


def load_ocr_engines() -> Tuple[PaddleOCR, Optional[PaddleOCR]]:
    """載入繁體中文模型與英文補強模型。"""
    print("📦 正在載入 PaddleOCR 繁體中文模型...")
    traditional_ocr = PaddleOCR(
        use_angle_cls=True,
        lang=TRADITIONAL_LANGUAGE,
        ocr_version=TRADITIONAL_OCR_VERSION,
        use_gpu=OCR_USE_GPU,
        enable_mkldnn=OCR_ENABLE_MKLDNN,
        ir_optim=False,  # Preserve the Server's patched PaddleOCR CPU compatibility.
        cpu_threads=OCR_CPU_THREADS,
        det_limit_side_len=OCR_DET_LIMIT_SIDE_LEN,
        det_limit_type="max",
        det_db_thresh=0.20,
        det_db_box_thresh=0.35,
        det_db_unclip_ratio=1.8,
        det_db_score_mode="slow",
        drop_score=OCR_ENGINE_DROP_SCORE,
        show_log=False,
    )

    english_ocr = None
    if RUN_EXTRA_ENGLISH_PASS:
        print("📦 正在載入 PaddleOCR 英文／數字模型...")
        english_ocr = PaddleOCR(
            use_angle_cls=True,
            lang=ENGLISH_LANGUAGE,
            ocr_version=ENGLISH_OCR_VERSION,
            use_gpu=OCR_USE_GPU,
            enable_mkldnn=OCR_ENABLE_MKLDNN,
            ir_optim=False,
            cpu_threads=OCR_CPU_THREADS,
            det_limit_side_len=OCR_DET_LIMIT_SIDE_LEN,
            det_limit_type="max",
            det_db_thresh=0.20,
            det_db_box_thresh=0.35,
            det_db_unclip_ratio=1.8,
            det_db_score_mode="slow",
            drop_score=OCR_ENGINE_DROP_SCORE,
            show_log=False,
        )

    print(f"⚙️ OCR 裝置：{'GPU' if OCR_USE_GPU else 'CPU'}")
    return traditional_ocr, english_ocr


def find_test_images(test_dir: Path) -> list:
    """遞迴尋找 test 資料夾內所有支援的圖片。"""
    if not test_dir.is_dir():
        raise FileNotFoundError(
            f"找不到 test 資料夾：{test_dir}\n"
            "請在程式旁建立 test 資料夾並放入照片。"
        )

    image_paths = [
        path.resolve()
        for path in test_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    image_paths.sort(key=lambda path: str(path).lower())

    if not image_paths:
        supported = ", ".join(sorted(IMAGE_EXTENSIONS))
        raise FileNotFoundError(
            f"test 資料夾內沒有可辨識的照片：{test_dir}\n"
            f"支援格式：{supported}"
        )

    return image_paths


def read_image(path: Path):
    """讀取圖片；np.fromfile 可支援 Windows 中文路徑與中文檔名。"""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到照片：{path}")

    try:
        image_bytes = np.fromfile(str(path), dtype=np.uint8)
        frame = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"讀取照片失敗：{path}") from error

    if frame is None:
        raise ValueError(f"檔案不是 OpenCV 可辨識的圖片：{path}")

    return frame, path


def save_processed_image(path: Path, frame) -> Path:
    """以 PNG 儲存最終 OCR 輸入，並支援 Windows 中文路徑。"""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    success, encoded = cv2.imencode(
        ".png",
        frame,
        [cv2.IMWRITE_PNG_COMPRESSION, 3],
    )
    if not success:
        raise RuntimeError(f"處理後圖片編碼失敗：{path}")

    try:
        encoded.tofile(str(path))
    except OSError as error:
        raise RuntimeError(f"無法儲存處理後圖片：{path}") from error

    return path


def preprocess_for_ocr(frame, max_upscale: float = OCR_MAX_UPSCALE):
    """放大小字、校正局部對比並適度銳化。"""
    height, width = frame.shape[:2]
    long_side = max(height, width)
    scale = min(max_upscale, OCR_TARGET_LONG_SIDE / long_side)
    scale = max(1.0, scale)

    if scale > 1.01:
        frame = cv2.resize(
            frame,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    # CLAHE 只調整亮度，減輕偏粉光源與局部明暗不均。
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)
    enhanced = cv2.cvtColor(
        cv2.merge((lightness, channel_a, channel_b)),
        cv2.COLOR_LAB2BGR,
    )

    # Unsharp mask：加強筆畫邊緣，但避免使用二值化破壞中文字形。
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.0)
    return cv2.addWeighted(enhanced, 1.6, blurred, -0.6, 0)


def upscale_for_ocr(image):
    """只供 OCR branch 使用的高品質放大、CLAHE 與輕微銳化。"""
    height, width = image.shape[:2]
    long_side = max(height, width)
    scale = min(OCR_UPSCALE, OCR_TARGET_LONG_SIDE / max(1, long_side))
    scale = max(1.0, scale)
    if scale > 1.01:
        enlarged = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_LANCZOS4,
        )
    else:
        enlarged = image.copy()

    # 預留未來 Real-ESRGAN 掛接點，但預設不載入任何額外模型或套件。
    if USE_AI_SUPER_RESOLUTION:
        print("WARNING: AI super-resolution hook is enabled but no model is configured.")

    lab = cv2.cvtColor(enlarged, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
    enhanced = cv2.cvtColor(
        cv2.merge((lightness, channel_a, channel_b)),
        cv2.COLOR_LAB2BGR,
    )
    blurred = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    return cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)


def iter_paddle_lines(result) -> Iterable[dict]:
    """取出 PaddleOCR 文字與信心度，不保留座標。"""
    if not result:
        return

    for page in result:
        if not page:
            continue

        for line in page:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                continue

            recognition = line[1]
            if not isinstance(recognition, (list, tuple)) or len(recognition) < 2:
                continue

            # 中文模型可能回傳簡體字；所有後續流程只使用繁體化結果。
            text = to_traditional_chinese(str(recognition[0]))
            try:
                confidence = float(recognition[1])
            except (TypeError, ValueError) as error:
                record_exception("ocr_result_parse", error)
                continue

            if text.strip() and confidence >= OCR_OUTPUT_MIN_CONFIDENCE:
                yield {
                    "text": text.strip(),
                    "confidence": round(confidence, 6),
                }


def extract_detected_boxes(result) -> list:
    """讀取文字框供自動裁切使用；這些座標不會輸出到終端。"""
    boxes = []
    if not result:
        return boxes

    for page in result:
        if not page:
            continue

        for line in page:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                continue

            try:
                points = np.asarray(line[0], dtype=np.float32).reshape(-1, 2)
            except (TypeError, ValueError) as error:
                record_exception("ocr_result_parse", error)
                continue

            if len(points) >= 4 and np.isfinite(points).all():
                boxes.append(points)

    return boxes


def select_dominant_text_cluster(boxes: list, frame_shape: tuple) -> list:
    """只保留鋁箔藥板上的主要文字群，排除背景反光造成的孤立誤框。

    中文及英文模型可能在相同藥板上產生多個相鄰文字框；以框中心距離建立
    空間群組後，優先選擇框數最多的群組。裁切和旋轉角度都只能使用此群組，
    不能再由整張背景上的所有框共同決定。
    """
    if len(boxes) <= 1:
        return boxes

    height, width = frame_shape[:2]
    diagonal = float(np.hypot(width, height))
    max_distance = diagonal * OCR_CLUSTER_DISTANCE_RATIO
    valid_boxes = []
    rectangles = []
    areas = []

    for box in boxes:
        min_xy = np.min(box, axis=0)
        max_xy = np.max(box, axis=0)
        box_width, box_height = max_xy - min_xy
        # 過大的框通常是燈具、牆面或反光，不是包裝上的一行文字。
        if box_width > width * 0.60 or box_height > height * 0.35:
            continue
        valid_boxes.append(box)
        rectangles.append((min_xy[0], min_xy[1], max_xy[0], max_xy[1]))
        areas.append(max(1.0, float(box_width * box_height)))

    if not valid_boxes:
        return boxes

    unvisited = set(range(len(valid_boxes)))
    components = []
    while unvisited:
        seed = unvisited.pop()
        component = [seed]
        queue = [seed]
        while queue:
            current = queue.pop()
            ax0, ay0, ax1, ay1 = rectangles[current]
            neighbours = []
            for index in list(unvisited):
                bx0, by0, bx1, by1 = rectangles[index]
                gap_x = max(0.0, ax0 - bx1, bx0 - ax1)
                gap_y = max(0.0, ay0 - by1, by0 - ay1)
                if float(np.hypot(gap_x, gap_y)) <= max_distance:
                    neighbours.append(index)
            for index in neighbours:
                unvisited.remove(index)
                component.append(index)
                queue.append(index)
        components.append(component)

    # 框數是主要依據；總文字框面積只用於同框數時的排序。
    best = max(
        components,
        key=lambda component: (
            len(component),
            sum(areas[index] for index in component),
        ),
    )
    return [valid_boxes[index] for index in best]


def estimate_text_angle(boxes: list) -> float:
    """以文字框上緣估算主要傾斜角度，使用加權中位數降低誤框影響。"""
    angle_weights = []

    for points in boxes:
        if len(points) < 4:
            continue

        delta_x = float(points[1][0] - points[0][0])
        delta_y = float(points[1][1] - points[0][1])
        edge_length = float(np.hypot(delta_x, delta_y))
        if edge_length < 5.0:
            continue

        angle = float(np.degrees(np.arctan2(delta_y, delta_x)))
        # 同一行文字的方向相差 180° 時視為相同方向。
        angle = (angle + 90.0) % 180.0 - 90.0
        angle_weights.append((angle, edge_length))

    if not angle_weights:
        return 0.0

    angle_weights.sort(key=lambda item: item[0])
    total_weight = sum(weight for _, weight in angle_weights)
    accumulated_weight = 0.0

    for angle, weight in angle_weights:
        accumulated_weight += weight
        if accumulated_weight >= total_weight / 2.0:
            return angle

    return angle_weights[-1][0]


def filter_boxes_by_text_angle(boxes: list) -> list:
    """只保留與主要文字方向一致的框，排除垂直支架及電線誤框。"""
    if len(boxes) <= 1:
        return boxes
    dominant_angle = estimate_text_angle(boxes)
    filtered = []
    for points in boxes:
        if len(points) < 4:
            continue
        delta_x = float(points[1][0] - points[0][0])
        delta_y = float(points[1][1] - points[0][1])
        angle = float(np.degrees(np.arctan2(delta_y, delta_x)))
        angle = (angle + 90.0) % 180.0 - 90.0
        difference = abs((angle - dominant_angle + 90.0) % 180.0 - 90.0)
        if difference <= OCR_CLUSTER_ANGLE_TOLERANCE:
            filtered.append(points)
    return filtered or boxes


def rotate_and_extract_package_roi(
    original_frame,
    detector_frame,
    boxes: list,
    estimated_angle: float,
):
    """同步旋轉原圖及文字框，再由文字群推估並裁出完整藥板 ROI。

    ``boxes`` 位於放大後的 ``detector_frame`` 座標系。函式先將座標映射回
    ``original_frame``，建立擴張畫布的 affine matrix，使用同一矩陣旋轉
    圖片與所有框點。文字框只負責定位，實際裁切會保留較大的 package
    padding，避免切掉文字群外側的條碼、劑量與鋁箔邊緣。
    """
    if not boxes:
        return original_frame.copy(), 0.0, [], False

    detector_height, detector_width = detector_frame.shape[:2]
    original_height, original_width = original_frame.shape[:2]
    scale_x = original_width / float(detector_width)
    scale_y = original_height / float(detector_height)

    mapped_boxes = []
    for box in boxes:
        mapped = np.asarray(box, dtype=np.float32).copy()
        mapped[:, 0] *= scale_x
        mapped[:, 1] *= scale_y
        mapped_boxes.append(mapped)

    correction_angle = float(estimated_angle)
    if (
        abs(correction_angle) < OCR_DESKEW_MIN_ANGLE
        or abs(correction_angle) > OCR_DESKEW_MAX_ANGLE
    ):
        correction_angle = 0.0

    center = (original_width / 2.0, original_height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, correction_angle, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    rotated_width = int(round(original_height * sine + original_width * cosine))
    rotated_height = int(round(original_height * cosine + original_width * sine))
    matrix[0, 2] += rotated_width / 2.0 - center[0]
    matrix[1, 2] += rotated_height / 2.0 - center[1]

    rotated_frame = cv2.warpAffine(
        original_frame,
        matrix,
        (rotated_width, rotated_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    all_points = np.concatenate(mapped_boxes, axis=0).reshape(-1, 1, 2)
    transformed_points = cv2.transform(all_points, matrix).reshape(-1, 2)
    min_x, min_y = np.min(transformed_points, axis=0)
    max_x, max_y = np.max(transformed_points, axis=0)
    group_width = max(1.0, float(max_x - min_x))
    group_height = max(1.0, float(max_y - min_y))
    padding_x = group_width * OCR_PACKAGE_PADDING_X
    padding_y = group_height * OCR_PACKAGE_PADDING_Y

    x0 = max(0, int(np.floor(min_x - padding_x)))
    y0 = max(0, int(np.floor(min_y - padding_y)))
    x1 = min(rotated_width, int(np.ceil(max_x + padding_x)))
    y1 = min(rotated_height, int(np.ceil(max_y + padding_y)))
    # 若文字框仍離任何 crop 邊界太近，就逐步擴張；座標全程 clamp。
    for _ in range(6):
        crop_width = max(1, x1 - x0)
        crop_height = max(1, y1 - y0)
        margins = (
            float(min_x - x0) / crop_width,
            float(x1 - max_x) / crop_width,
            float(min_y - y0) / crop_height,
            float(y1 - max_y) / crop_height,
        )
        expand_left = margins[0] < OCR_MIN_EDGE_MARGIN_RATIO and x0 > 0
        expand_right = margins[1] < OCR_MIN_EDGE_MARGIN_RATIO and x1 < rotated_width
        expand_top = margins[2] < OCR_MIN_EDGE_MARGIN_RATIO and y0 > 0
        expand_bottom = margins[3] < OCR_MIN_EDGE_MARGIN_RATIO and y1 < rotated_height
        if not any((expand_left, expand_right, expand_top, expand_bottom)):
            break
        step_x = max(1, int(math.ceil(group_width * 0.10)))
        step_y = max(1, int(math.ceil(group_height * 0.10)))
        if expand_left:
            x0 = max(0, x0 - step_x)
        if expand_right:
            x1 = min(rotated_width, x1 + step_x)
        if expand_top:
            y0 = max(0, y0 - step_y)
        if expand_bottom:
            y1 = min(rotated_height, y1 + step_y)

    if x1 <= x0 or y1 <= y0:
        return original_frame.copy(), 0.0, [], False

    cropped = rotated_frame[y0:y1, x0:x1].copy()
    transformed_boxes = []
    for box in mapped_boxes:
        transformed = cv2.transform(box.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        transformed[:, 0] -= x0
        transformed[:, 1] -= y0
        transformed_boxes.append(transformed)
    return cropped, round(correction_angle, 2), transformed_boxes, True


def run_ocr(engine: PaddleOCR, frame, label="OCR") -> list:
    """執行一次 OCR 並直接回傳原始辨識結果。"""
    with span(label) as event:
        event["input_shape"] = list(frame.shape)
        raw = engine.ocr(frame, cls=True)
        event["raw_result"] = raw
        lines = list(iter_paddle_lines(raw))
        event["filtered_lines"] = lines
        return lines


def merge_ocr_lines(*line_groups: list) -> list:
    """合併多方向結果；相同文字只保留信心度最高者。"""
    best = {}
    for lines in line_groups:
        for line in lines:
            text = line["text"].strip()
            if text and (
                text not in best
                or line["confidence"] > best[text]["confidence"]
            ):
                best[text] = line
    return sorted(best.values(), key=lambda item: item["confidence"], reverse=True)


def combine_captured_text(chinese_lines: list, english_lines: list) -> list:
    """直接整合兩個模型抓到的內容，轉繁體並以最高信心度去重。"""
    combined = {}
    for source, lines in (
        ("中文模型", chinese_lines),
        ("英文模型", english_lines),
    ):
        for line in lines:
            text = to_traditional_chinese(line["text"]).strip()
            if not text:
                continue
            confidence = float(line["confidence"])
            previous = combined.get(text)
            if previous is None or confidence > previous["confidence"]:
                combined[text] = {
                    "text": text,
                    "confidence": confidence,
                    "source": source,
                }
    return sorted(
        combined.values(),
        key=lambda item: item["confidence"],
        reverse=True,
    )


def calculate_orientation_score(chinese_lines: list, english_lines: list) -> tuple:
    """計算方向品質；回傳可比較的分數及明細。"""
    lines = merge_ocr_lines(chinese_lines, english_lines)
    confidences = [float(line["confidence"]) for line in lines]
    combined_text = "".join(line["text"] for line in lines)
    english_count = len(re.findall(r"[A-Za-z]", combined_text))
    chinese_count = len(re.findall(r"[\u3400-\u9fff]", combined_text))
    digit_count = len(re.findall(r"\d", combined_text))
    valid_length = english_count + chinese_count + digit_count
    count = len(lines)
    confidence_sum = sum(confidences)
    confidence_average = confidence_sum / count if count else 0.0
    # 文字數、信心度總和/平均和有效字數都納入；tuple 第一項供直接比較。
    score = (
        count
        + confidence_sum
        + confidence_average
        + valid_length * 0.02
        + english_count * 0.005
        + chinese_count * 0.008
        + digit_count * 0.003
    )
    return score, {
        "count": count,
        "confidence_sum": round(confidence_sum, 6),
        "confidence_average": round(confidence_average, 6),
        "valid_length": valid_length,
        "english_characters": english_count,
        "chinese_characters": chinese_count,
        "digits": digit_count,
    }


def ocr_text_quality(lines: list) -> dict:
    """Score useful OCR content without rewarding one-character fragments."""
    merged = merge_ocr_lines(lines)
    weighted_confidence = 0.0
    valid_characters = 0
    useful_line_count = 0
    longest_line = 0
    quality_score = 0.0
    for line in merged:
        text = str(line.get("text", ""))
        confidence = float(line.get("confidence", 0.0))
        valid_length = len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text))
        if not valid_length:
            continue
        valid_characters += valid_length
        weighted_confidence += confidence * valid_length
        longest_line = max(longest_line, valid_length)
        if valid_length >= 3:
            useful_line_count += 1
        quality_score += confidence * max(0, valid_length - 1)

    average_confidence = (
        weighted_confidence / valid_characters if valid_characters else 0.0
    )
    quality_score += longest_line * 0.25 + useful_line_count * 0.5
    return {
        "score": round(quality_score, 6),
        "average_confidence": round(average_confidence, 6),
        "valid_characters": valid_characters,
        "useful_line_count": useful_line_count,
        "longest_line": longest_line,
    }


def orientation_confidence_dominates(
    alternative_details: dict,
    score_winner_details: dict,
) -> bool:
    """Whether confidence quality should override the raw orientation score."""
    return bool(
        alternative_details.get("count", 0) > 0
        and alternative_details.get("confidence_sum", 0.0)
        > score_winner_details.get("confidence_sum", 0.0)
        and alternative_details.get("confidence_average", 0.0)
        >= score_winner_details.get("confidence_average", 0.0)
        + ORIENTATION_CONFIDENCE_AVERAGE_OVERRIDE_GAP
    )


def select_ocr_orientation(
    frame,
    traditional_ocr: PaddleOCR,
    english_ocr: Optional[PaddleOCR],
):
    """Use English for orientation, with Chinese fallback only when ambiguous."""
    orientation_started = time.perf_counter()
    pass_count = 0

    def timed_ocr(label: str, engine: Optional[PaddleOCR], image) -> tuple:
        nonlocal pass_count
        if engine is None:
            if OCR_ORIENTATION_DEBUG:
                print(f"{label:<20}: skipped")
            return [], 0.0
        started = time.perf_counter()
        lines = run_ocr(engine, image, label)
        elapsed = time.perf_counter() - started
        pass_count += 1
        if OCR_ORIENTATION_DEBUG:
            print(f"{label:<20}: {elapsed:.3f} sec")
        return lines, elapsed

    height, width = frame.shape[:2]
    frame_180 = cv2.rotate(frame, cv2.ROTATE_180)
    ocr_input_0 = upscale_for_ocr(frame)
    ocr_input_180 = cv2.rotate(ocr_input_0, cv2.ROTATE_180)

    # Tiny crops do not contain enough pixels for a meaningful 0°/180° race.
    # Keep 0° and run each language at most once.
    if width < ORIENTATION_MIN_WIDTH or height < ORIENTATION_MIN_HEIGHT:
        english_0, _ = timed_ocr("English OCR 0°", english_ocr, ocr_input_0)
        traditional_0, _ = timed_ocr(
            "Chinese OCR final", traditional_ocr, ocr_input_0
        )
        score_0, details_0 = calculate_orientation_score(
            traditional_0, english_0
        )
        _, details_180 = calculate_orientation_score([], [])
        scores = {
            "0": {"score": round(score_0, 6), **details_0},
            "180": {"score": 0.0, **details_180},
            "decision": "small ROI: orientation competition skipped",
            "ocr_pass_count": pass_count,
        }
        if OCR_ORIENTATION_DEBUG:
            print("English OCR 180°    : skipped (small ROI)")
            print(
                f"Orientation total   : "
                f"{time.perf_counter() - orientation_started:.3f} sec"
            )
            print(f"Total OCR passes    : {pass_count}")
        return frame, ocr_input_0, traditional_0, english_0, "0°", scores

    english_0, _ = timed_ocr("English OCR 0°", english_ocr, ocr_input_0)
    english_180, _ = timed_ocr("English OCR 180°", english_ocr, ocr_input_180)
    english_score_0, english_details_0 = calculate_orientation_score([], english_0)
    english_score_180, english_details_180 = calculate_orientation_score(
        [], english_180
    )
    english_margin = abs(english_score_180 - english_score_0)
    best_english_details = (
        english_details_180
        if english_score_180 > english_score_0
        else english_details_0
    )
    english_decisive = (
        english_ocr is not None
        and best_english_details["count"] > 0
        and best_english_details["confidence_average"]
        >= ORIENTATION_MIN_AVERAGE_CONFIDENCE
        and english_margin >= ORIENTATION_MIN_SCORE_MARGIN
    )

    if english_decisive:
        use_180 = english_score_180 > english_score_0
        score_winner_details = (
            english_details_180 if use_180 else english_details_0
        )
        alternative_details = (
            english_details_0 if use_180 else english_details_180
        )
        confidence_override = orientation_confidence_dominates(
            alternative_details,
            score_winner_details,
        )
        if confidence_override:
            use_180 = not use_180
        final_ocr_input = ocr_input_180 if use_180 else ocr_input_0
        traditional_final, _ = timed_ocr(
            "Chinese OCR final", traditional_ocr, final_ocr_input
        )
        english_final = english_180 if use_180 else english_0
        score_0, details_0 = english_score_0, english_details_0
        score_180, details_180 = english_score_180, english_details_180
        decision = (
            "English confidence-quality override"
            if confidence_override
            else "English score margin"
        )
    else:
        # Only ambiguous/empty English evidence pays for Chinese 0° + 180°.
        traditional_0, chinese_time_0 = timed_ocr(
            "Chinese OCR 0° fallback", traditional_ocr, ocr_input_0
        )
        traditional_180, chinese_time_180 = timed_ocr(
            "Chinese OCR 180° fallback", traditional_ocr, ocr_input_180
        )
        score_0, details_0 = calculate_orientation_score(
            traditional_0, english_0
        )
        score_180, details_180 = calculate_orientation_score(
            traditional_180, english_180
        )
        use_180 = score_180 > score_0
        final_ocr_input = ocr_input_180 if use_180 else ocr_input_0
        traditional_final = traditional_180 if use_180 else traditional_0
        english_final = english_180 if use_180 else english_0
        if OCR_ORIENTATION_DEBUG:
            reused_time = chinese_time_180 if use_180 else chinese_time_0
            print(f"Chinese OCR final   : reused fallback ({reused_time:.3f} sec)")
        decision = "Chinese fallback"

    scores = {
        "0": {"score": round(score_0, 6), **details_0},
        "180": {"score": round(score_180, 6), **details_180},
        "ocr_pass_count": pass_count,
        "english_margin": round(english_margin, 6),
        "decision": decision,
    }
    if OCR_ORIENTATION_DEBUG:
        print(
            f"Orientation total   : "
            f"{time.perf_counter() - orientation_started:.3f} sec"
        )
        print(f"Total OCR passes    : {pass_count}")
    if use_180:
        return (
            frame_180, final_ocr_input, traditional_final,
            english_final, "180°", scores,
        )
    return frame, final_ocr_input, traditional_final, english_final, "0°", scores


def read_barcodes_compatible(image) -> list:
    """以新 API 參數優先呼叫 zxingcpp，舊版不支援時逐級降級。"""
    keyword_sets = [
        {
            "try_rotate": True,
            "try_downscale": True,
            "try_invert": True,
            "return_errors": True,
        },
        {"try_rotate": True, "try_downscale": True, "try_invert": True},
        {"try_rotate": True, "try_downscale": True},
        {},
    ]
    for kwargs in keyword_sets:
        try:
            return list(zxingcpp.read_barcodes(image, **kwargs))
        except TypeError as error:
            record_exception("barcode_api_compatibility", error)
            continue
        except Exception as error:
            record_exception("barcode_decode", error)
            return []
    return []


def barcode_result_item(barcode) -> Optional[dict]:
    from barcode_pipeline import result_item
    return result_item(barcode)


def barcode_quality(candidate, gray_candidate) -> dict:
    """計算候選區清晰度、過曝率、垂直邊緣及排序分數。"""
    sharpness = float(cv2.Laplacian(gray_candidate, cv2.CV_64F).var())
    overexposure = float(np.mean(gray_candidate >= 245))
    vertical_gradient = float(
        np.mean(np.abs(cv2.Sobel(gray_candidate, cv2.CV_32F, 1, 0, ksize=3)))
    )
    height, width = gray_candidate.shape[:2]
    aspect_ratio = width / max(1.0, float(height))
    score = (
        math.log1p(sharpness)
        + vertical_gradient * 0.08
        + (1.0 - overexposure) * 6.0
        + min(aspect_ratio, 6.0)
    )
    return {
        "image": candidate,
        "width": width,
        "height": height,
        "sharpness": sharpness,
        "overexposure": overexposure,
        "vertical_gradient": vertical_gradient,
        "aspect_ratio": aspect_ratio,
        "quality_score": score,
    }


def group_profile_indices(indices, max_gap: int) -> list:
    """將 projection profile 中相鄰或只有小間隙的 index 合成區段。"""
    if len(indices) == 0:
        return []
    groups = []
    start = previous = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value - previous > max_gap + 1:
            groups.append((start, previous + 1))
            start = value
        previous = value
    groups.append((start, previous + 1))
    return groups


def expand_barcode_core(
    package_roi, vertical_edge_map, core_bbox, return_body: bool = False
) -> tuple:
    """由 stripe core 沿 row/column edge density 擴張，再加入 quiet zone。"""
    image_height, image_width = vertical_edge_map.shape[:2]
    x, y, width, height = core_bbox
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image_width, x + width), min(image_height, y + height)
    center_x = (x0 + x1) // 2
    center_y = (y0 + y1) // 2
    gap_x = max(1, int(round(image_width * BARCODE_PROFILE_MAX_GAP_RATIO)))
    gap_y = max(1, int(round(image_height * 0.012)))

    # X/Y 互相影響，做兩輪 projection 擴張可從局部 core 回復完整條紋。
    for _ in range(2):
        region = vertical_edge_map[y0:y1, :]
        column_profile = np.mean(region > 0, axis=0) if region.size else np.zeros(image_width)
        peak = float(np.max(column_profile)) if column_profile.size else 0.0
        active_columns = np.flatnonzero(
            column_profile >= max(0.05, peak * BARCODE_COLUMN_DENSITY_RATIO)
        )
        column_groups = group_profile_indices(active_columns, gap_x)
        containing = [group for group in column_groups if group[0] <= center_x < group[1]]
        if containing:
            x0, x1 = containing[0]

        region = vertical_edge_map[:, x0:x1]
        row_profile = np.mean(region > 0, axis=1) if region.size else np.zeros(image_height)
        peak = float(np.max(row_profile)) if row_profile.size else 0.0
        active_rows = np.flatnonzero(
            row_profile >= max(0.04, peak * BARCODE_ROW_DENSITY_RATIO)
        )
        row_groups = group_profile_indices(active_rows, gap_y)
        containing = [group for group in row_groups if group[0] <= center_y < group[1]]
        if containing:
            y0, y1 = containing[0]

    expanded_width = max(1, x1 - x0)
    expanded_height = max(1, y1 - y0)
    pad_x = int(round(expanded_width * BARCODE_PADDING_X))
    pad_y = int(round(expanded_height * BARCODE_PADDING_Y))
    body_box = (x0, y0, x1, y1)
    final_box = (
        max(0, x0 - pad_x),
        max(0, y0 - pad_y),
        min(image_width, x1 + pad_x),
        min(image_height, y1 + pad_y),
    )
    # Stripe quality must be measured on the expanded barcode body.  Measuring
    # the padded ROI would dilute the line density with the quiet zone and the
    # human-readable digits below the barcode.
    return (final_box, body_box) if return_body else final_box


def barcode_stripe_metrics(gray, vertical_edge_map, bbox) -> dict:
    """驗證條紋數、共同高度、edge density 及 X/Y gradient 比例。"""
    x0, y0, x1, y1 = bbox
    edge = vertical_edge_map[y0:y1, x0:x1] > 0
    region = gray[y0:y1, x0:x1]
    height, width = edge.shape[:2]
    if height < 2 or width < 2:
        return {"accepted": False, "reason": "empty"}

    column_density = np.mean(edge, axis=0)
    active = np.flatnonzero(column_density >= 0.25)
    stripe_groups = group_profile_indices(active, 1)
    stripe_heights = []
    stripe_continuities = []
    for start, end in stripe_groups:
        row_hits = np.any(edge[:, start:end], axis=1).astype(np.uint8)
        ys = np.flatnonzero(row_hits)
        if len(ys):
            stripe_heights.append((int(ys[-1]) - int(ys[0]) + 1) / height)
            runs = group_profile_indices(ys, 0)
            longest_run = max((end_y - start_y for start_y, end_y in runs), default=0)
            stripe_continuities.append(longest_run / height)

    median_height = float(np.median(stripe_heights)) if stripe_heights else 0.0
    height_mad = (
        float(np.median(np.abs(np.asarray(stripe_heights) - median_height)))
        if stripe_heights else 1.0
    )
    vertical_continuity = (
        float(np.median(stripe_continuities)) if stripe_continuities else 0.0
    )
    gradient_x = float(np.mean(np.abs(cv2.Sobel(region, cv2.CV_32F, 1, 0, ksize=3))))
    gradient_y = float(np.mean(np.abs(cv2.Sobel(region, cv2.CV_32F, 0, 1, ksize=3))))
    gradient_ratio = gradient_x / max(1e-6, gradient_y)
    stripe_density = float(np.mean(edge))
    aspect_ratio = width / max(1.0, float(height))
    reasons = []
    if aspect_ratio < BARCODE_MIN_ASPECT_RATIO:
        reasons.append("aspect ratio too small")
    if aspect_ratio > BARCODE_MAX_ASPECT_RATIO:
        reasons.append("aspect ratio too large")
    if len(stripe_groups) < BARCODE_MIN_STRIPE_COUNT:
        reasons.append("insufficient stripe count")
    if stripe_density < BARCODE_MIN_STRIPE_DENSITY:
        reasons.append("low stripe density")
    if median_height < BARCODE_MIN_STRIPE_HEIGHT_RATIO:
        reasons.append("short vertical stripes")
    if height_mad > BARCODE_MAX_STRIPE_HEIGHT_MAD:
        reasons.append("stripe height inconsistency")
    if vertical_continuity < BARCODE_MIN_VERTICAL_CONTINUITY:
        reasons.append("low vertical continuity")
    if gradient_ratio < BARCODE_MIN_XY_GRADIENT_RATIO:
        reasons.append("X/Y gradient ratio too low")
    # Joint structural checks: letters can have vertical strokes but usually
    # lack many co-directed, similarly long bars across most of the body.
    gx = cv2.Sobel(region, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(region, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.hypot(gx, gy)
    orientation_coherence = float(np.hypot(np.sum(gx*gx-gy*gy), np.sum(2*gx*gy))
                                  / max(float(np.sum(magnitude*magnitude)), 1e-6))
    centers = np.asarray([(a+b)/2 for a,b in stripe_groups])
    gaps = np.diff(centers)
    spacing_cv = float(np.std(gaps)/max(float(np.mean(gaps)), 1e-6)) if len(gaps) else 99.
    valid_bars = sum(h >= .40 and c >= .40 for h,c in zip(stripe_heights, stripe_continuities))
    stripe_coverage = float((active[-1]-active[0]+1)/width) if len(active) else 0.
    if valid_bars < 8:
        reasons.append("too few long continuous parallel bars")
    if orientation_coherence < .30:
        reasons.append("inconsistent line direction")
    if spacing_cv > 1.2:
        reasons.append("irregular stripe spacing")
    if stripe_coverage < .55:
        reasons.append("stripe region occupies too little of ROI")
    accepted = not reasons
    return {
        "accepted": accepted,
        "stripe_count": len(stripe_groups),
        "stripe_density": stripe_density,
        "stripe_height_median": median_height,
        "stripe_height_mad": height_mad,
        "vertical_continuity": vertical_continuity,
        "gradient_ratio": gradient_ratio,
        "aspect_ratio": aspect_ratio,
        "valid_bar_count": valid_bars,
        "orientation_coherence": orientation_coherence,
        "spacing_cv": spacing_cv,
        "stripe_coverage": stripe_coverage,
        "reasons": reasons,
    }


def split_large_barcode_candidate(vertical_edge_map, bbox) -> list:
    """在混合文字/多條碼的大框內重新以 Y band + X group 切子 core。"""
    x0, y0, x1, y1 = bbox
    region = vertical_edge_map[y0:y1, x0:x1] > 0
    region_height, region_width = region.shape[:2]
    if region_height < 4 or region_width < 8:
        return []

    row_profile = np.mean(region, axis=1)
    smoothed = cv2.GaussianBlur(row_profile.reshape(-1, 1), (1, 3), 0).ravel()
    positive = smoothed[smoothed > 0]
    threshold = (
        max(0.06, float(np.percentile(positive, 70)) * 0.82)
        if len(positive) else 1.0
    )
    row_groups = group_profile_indices(np.flatnonzero(smoothed >= threshold), 1)
    sub_cores = []
    max_x_gap = max(1, int(round(region_width * BARCODE_PROFILE_MAX_GAP_RATIO)))
    for local_y0, local_y1 in row_groups:
        band_height = local_y1 - local_y0
        if band_height < max(3, int(round(region_height * 0.035))):
            continue
        band = region[local_y0:local_y1, :]
        column_profile = np.mean(band, axis=0)
        active_columns = np.flatnonzero(column_profile >= 0.28)
        for local_x0, local_x1 in group_profile_indices(active_columns, max_x_gap):
            band_width = local_x1 - local_x0
            if band_width < max(8, int(round(region_width * 0.12))):
                continue
            sub_cores.append((
                x0 + local_x0,
                y0 + local_y0,
                band_width,
                band_height,
            ))
    return sub_cores


def detect_barcode_candidates(package_roi) -> tuple:
    """以 scanline/projection 找 stripe core，再擴張成完整 barcode ROI。"""
    gray = cv2.cvtColor(package_roi, cv2.COLOR_BGR2GRAY)
    image_height, image_width = gray.shape[:2]
    sobel_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    directional = np.where(sobel_x > sobel_y * 1.10, sobel_x, 0)
    normalized = cv2.normalize(directional, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, vertical_edges = cv2.threshold(
        normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # Scanline：先找連續多 row 都有高 vertical-edge density 的 Y bands。
    row_profile = np.mean(vertical_edges > 0, axis=1)
    smoothed_rows = cv2.GaussianBlur(row_profile.reshape(-1, 1), (1, 5), 0).ravel()
    positive_rows = smoothed_rows[smoothed_rows > 0]
    row_threshold = (
        max(0.035, float(np.percentile(positive_rows, 65)) * 0.72)
        if len(positive_rows) else 1.0
    )
    row_indices = np.flatnonzero(smoothed_rows >= row_threshold)
    y_bands = group_profile_indices(
        row_indices, max(1, int(round(image_height * 0.015)))
    )

    cores = []
    max_x_gap = max(2, int(round(image_width * BARCODE_PROFILE_MAX_GAP_RATIO)))
    for y0, y1 in y_bands:
        if y1 - y0 < max(3, int(round(image_height * 0.018))):
            continue
        band = vertical_edges[y0:y1, :] > 0
        column_profile = np.mean(band, axis=0)
        active_columns = np.flatnonzero(column_profile >= 0.25)
        for x0, x1 in group_profile_indices(active_columns, max_x_gap):
            if x1 - x0 < max(8, int(round(image_width * 0.05))):
                continue
            cores.append((x0, y0, x1 - x0, y1 - y0))

    candidates = []
    debug_entries = []
    accepted_boxes = []

    def accept_entry(entry):
        final_box = entry["final"]
        x0, y0, x1, y1 = final_box
        for old_x0, old_y0, old_x1, old_y1 in accepted_boxes:
            intersection = max(0, min(x1, old_x1) - max(x0, old_x0)) * max(
                0, min(y1, old_y1) - max(y0, old_y0)
            )
            union = (
                (x1 - x0) * (y1 - y0)
                + (old_x1 - old_x0) * (old_y1 - old_y0)
                - intersection
            )
            if union > 0 and intersection / union > 0.55:
                entry["accepted"] = False
                entry["reasons"] = ["duplicate candidate"]
                return
        accepted_boxes.append(final_box)
        crop = package_roi[y0:y1, x0:x1].copy()
        quality = barcode_quality(crop, gray[y0:y1, x0:x1])
        quality.update({
            key: value for key, value in entry.items()
            if key not in {"index", "label", "kind", "core", "final"}
        })
        quality["box"] = final_box
        quality["core_box"] = entry["core"]
        quality["label"] = entry["label"]
        candidates.append(quality)

    for core_index, core in enumerate(cores, start=1):
        final_box, body_box = expand_barcode_core(
            package_roi, vertical_edges, core, return_body=True
        )
        metrics = barcode_stripe_metrics(gray, vertical_edges, body_box)
        x0, y0, x1, y1 = final_box
        box_width, box_height = x1 - x0, y1 - y0
        box_aspect = box_width / max(1.0, float(box_height))
        area_ratio = (box_width * box_height) / max(1.0, image_width * image_height)
        is_large_mixed = (
            box_aspect < BARCODE_MIN_ASPECT_RATIO
            or box_height > image_height * BARCODE_LARGE_HEIGHT_RATIO
            or area_ratio > BARCODE_LARGE_AREA_RATIO
        )
        entry = {
            "index": core_index,
            "label": f"C{core_index}",
            "kind": "raw",
            "core": core,
            "body": body_box,
            "final": final_box,
            **metrics,
        }
        debug_entries.append(entry)

        if metrics["accepted"] and not is_large_mixed:
            accept_entry(entry)
            continue
        if not is_large_mixed:
            continue

        entry["kind"] = "split_parent"
        entry["accepted"] = False
        entry["reasons"] = ["large mixed-content region"]
        sub_cores = split_large_barcode_candidate(vertical_edges, final_box)
        unique_sub_boxes = []
        child_index = 0
        for sub_core in sub_cores:
            sub_box, sub_body = expand_barcode_core(
                package_roi, vertical_edges, sub_core, return_body=True
            )
            sx0, sy0, sx1, sy1 = sub_box
            duplicate = False
            for ux0, uy0, ux1, uy1 in unique_sub_boxes:
                intersection = max(0, min(sx1, ux1) - max(sx0, ux0)) * max(
                    0, min(sy1, uy1) - max(sy0, uy0)
                )
                union = (
                    (sx1 - sx0) * (sy1 - sy0)
                    + (ux1 - ux0) * (uy1 - uy0)
                    - intersection
                )
                if union > 0 and intersection / union > 0.55:
                    duplicate = True
                    break
            if duplicate:
                continue
            unique_sub_boxes.append(sub_box)
            child_index += 1
            sub_metrics = barcode_stripe_metrics(gray, vertical_edges, sub_body)
            # Do not re-promote a mixed-content parent through its expanded child.
            if ((sx1-sx0)*(sy1-sy0) > image_width*image_height*BARCODE_LARGE_AREA_RATIO
                    or sy1-sy0 > image_height*BARCODE_LARGE_HEIGHT_RATIO):
                sub_metrics["accepted"] = False
                sub_metrics.setdefault("reasons", []).append("mixed-content child too large")
            child = {
                "index": core_index,
                "label": f"C{core_index}-{child_index}",
                "kind": "split_child",
                "core": sub_core,
                "body": sub_body,
                "final": sub_box,
                **sub_metrics,
            }
            debug_entries.append(child)
            if child["accepted"]:
                accept_entry(child)

    candidates.sort(key=lambda item: item["quality_score"], reverse=True)
    candidates = candidates[:BARCODE_MAX_CANDIDATES]

    debug_image = package_roi.copy()
    for entry in debug_entries:
        entry.update(source='BARCODE_CANDIDATE', decode_success=False,
                     decode_attempted=False, weight=0)
        x, y, width, height = entry["core"]
        color = (0, 255, 255)  # 黃色 core
        cv2.rectangle(debug_image, (x, y), (x + width, y + height), color, 1)
        x0, y0, x1, y1 = entry["final"]
        final_color = (0, 165, 255) if entry["accepted"] else (128, 128, 128)
        cv2.rectangle(debug_image, (x0, y0), (x1, y1), final_color, 2)
        cv2.putText(
            debug_image,
            entry["label"] + (" BARCODE_CANDIDATE decode=NOT_TRIED" if entry['accepted'] else " REJECTED_GEOMETRY"),
            (x0, max(12, y0 - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            final_color,
            1,
            cv2.LINE_AA,
        )
    return candidates, debug_image, debug_entries


def decode_barcode_candidate(image) -> list:
    from barcode_pipeline import decode_roi
    return decode_roi(image, read_barcodes_compatible)


def run_barcode_pipeline(original_frame, package_roi, image_path: Path, save_debug=True) -> dict:
    """ZXing first; candidate geometry is debug-only and never evidence."""
    from barcode_pipeline import run
    debug_dir = DEFAULT_BARCODE_DEBUG_DIR / image_path.parent.name if save_debug else None
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        for stale in debug_dir.glob(f"{image_path.stem}_candidate_*.png"):
            stale.unlink()
        for stale in debug_dir.glob(f"{image_path.stem}_qr_*.png"):
            stale.unlink()
    return run(original_frame, image_path, read_barcodes_compatible,
               detect_barcode_candidates, debug_dir)


def rotate_full_image_for_ocr(frame, angle: float):
    """Deskew the complete canvas without cropping any image content."""
    correction = float(angle)
    if abs(correction) < OCR_DESKEW_MIN_ANGLE or abs(correction) > OCR_DESKEW_MAX_ANGLE:
        return frame.copy(), 0.0
    height, width = frame.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, correction, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    output_width = int(round(height * sine + width * cosine))
    output_height = int(round(height * cosine + width * sine))
    matrix[0, 2] += output_width / 2.0 - center[0]
    matrix[1, 2] += output_height / 2.0 - center[1]
    rotated = cv2.warpAffine(
        frame, matrix, (output_width, output_height), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )
    return rotated, round(correction, 2)


def rotate_image_bound(frame, angle: float):
    """Rotate an ROI without clipping; unlike normal deskew, allow any angle."""
    height, width = frame.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    output_width = int(round(height * sine + width * cosine))
    output_height = int(round(height * cosine + width * sine))
    matrix[0, 2] += output_width / 2.0 - center[0]
    matrix[1, 2] += output_height / 2.0 - center[1]
    return cv2.warpAffine(
        frame,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def text_roi_bounds_from_boxes(frame, detector_shape: tuple, boxes: list):
    """Map detected text boxes to the source image and return a padded ROI."""
    if not boxes:
        return None
    frame_height, frame_width = frame.shape[:2]
    detector_height, detector_width = detector_shape[:2]
    if detector_width <= 0 or detector_height <= 0:
        return None

    points = np.concatenate(
        [np.asarray(box, dtype=np.float32).reshape(-1, 2) for box in boxes],
        axis=0,
    )
    points[:, 0] *= frame_width / float(detector_width)
    points[:, 1] *= frame_height / float(detector_height)
    min_x, min_y = np.min(points, axis=0)
    max_x, max_y = np.max(points, axis=0)
    group_width = max(1.0, float(max_x - min_x))
    group_height = max(1.0, float(max_y - min_y))
    if group_width < 12 or group_height < 12:
        return None

    padding_x = max(group_width * 0.90, frame_width * 0.05)
    padding_y = max(group_height * 0.90, frame_height * 0.05)
    x0 = max(0, int(math.floor(min_x - padding_x)))
    y0 = max(0, int(math.floor(min_y - padding_y)))
    x1 = min(frame_width, int(math.ceil(max_x + padding_x)))
    y1 = min(frame_height, int(math.ceil(max_y + padding_y)))
    if x1 - x0 < 40 or y1 - y0 < 40:
        return None
    return [x0, y0, x1, y1]


def recognize_photo_angle_fallback(
    frame,
    base_result: dict,
    traditional_ocr: PaddleOCR,
    english_ocr: Optional[PaddleOCR],
):
    """Return a higher-quality rotated-ROI OCR candidate, or ``None``.

    Barcode fields are inherited unchanged from ``base_result``. This helper
    is called only after the normal pair-level database match has failed.
    """
    bbox = base_result.get("angle_fallback_roi")
    if not bbox or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = (int(value) for value in bbox)
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    started = time.perf_counter()
    english_candidates = []
    for angle in ANGLE_FALLBACK_ANGLES:
        ocr_input = preprocess_for_ocr(rotate_image_bound(roi, angle))
        english_lines = (
            run_ocr(english_ocr, ocr_input, f"Angle fallback English {angle:+d}")
            if english_ocr is not None
            else []
        )
        english_candidates.append({
            "angle": angle,
            "ocr_input": ocr_input,
            "english_lines": english_lines,
            "english_quality": ocr_text_quality(english_lines),
        })

    shortlisted = sorted(
        english_candidates,
        key=lambda item: (
            item["english_quality"]["score"],
            item["english_quality"]["average_confidence"],
        ),
        reverse=True,
    )[:ANGLE_FALLBACK_TOP_ENGLISH]

    completed = []
    for candidate in shortlisted:
        traditional_lines = run_ocr(
            traditional_ocr,
            candidate["ocr_input"],
            f"Angle fallback Chinese {candidate['angle']:+d}",
        )
        combined_lines = merge_ocr_lines(
            traditional_lines, candidate["english_lines"]
        )
        completed.append({
            **candidate,
            "traditional_lines": traditional_lines,
            "quality": ocr_text_quality(combined_lines),
        })

    if not completed:
        return None
    best = max(
        completed,
        key=lambda item: (
            item["quality"]["score"],
            item["quality"]["average_confidence"],
        ),
    )
    baseline_quality = ocr_text_quality(base_result.get("captured_text", []))
    fallback_quality = best["quality"]
    meaningful_gain = (
        fallback_quality["score"]
        >= baseline_quality["score"] + ANGLE_FALLBACK_MIN_SCORE_GAIN
        and fallback_quality["valid_characters"]
        >= baseline_quality["valid_characters"]
        + ANGLE_FALLBACK_MIN_VALID_CHAR_GAIN
        and fallback_quality["average_confidence"]
        >= max(
            OCR_OUTPUT_MIN_CONFIDENCE,
            baseline_quality["average_confidence"]
            - ANGLE_FALLBACK_MAX_AVERAGE_CONFIDENCE_DROP,
        )
    )
    if not meaningful_gain:
        return None

    traditional_lines = merge_ocr_lines(
        base_result.get("traditional_ocr", []), best["traditional_lines"]
    )
    english_lines = merge_ocr_lines(
        base_result.get("english_ocr", []), best["english_lines"]
    )
    captured_text = combine_captured_text(traditional_lines, english_lines)
    for item in captured_text:
        item["raw"] = item["text"]
        item["normalized"] = re.sub(
            r"[^a-z0-9\u3400-\u9fff]+", "", item["text"].casefold()
        )
        item["source"] = "angle_fallback"

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    timing = dict(base_result.get("timing", {}))
    timing["ocr_time_ms"] = round(timing.get("ocr_time_ms", 0.0) + elapsed_ms, 2)
    timing["photo_inference_time_ms"] = round(
        timing.get("photo_inference_time_ms", 0.0) + elapsed_ms, 2
    )
    return {
        **base_result,
        "traditional_ocr": traditional_lines,
        "english_ocr": english_lines,
        "captured_text": captured_text,
        "roi_used": True,
        "text_source": "full_image+angle_fallback",
        "orientation": f"angle_fallback_{best['angle']:+d}",
        "angle_fallback": {
            "attempted": True,
            "adopted": False,
            "angle": best["angle"],
            "roi": bbox,
            "baseline_quality": baseline_quality,
            "fallback_quality": fallback_quality,
            "elapsed_ms": elapsed_ms,
        },
        "timing": timing,
    }


def _recognize_photo_legacy_roi(
    frame,
    image_path: Path,
    processed_path: Path,
    traditional_ocr: PaddleOCR,
    english_ocr: Optional[PaddleOCR],
    write_outputs: bool = True,
) -> dict:
    """辨識單張照片，不做關鍵字整理或資料庫比對。"""
    inference_started_ns = time.perf_counter_ns()
    preprocess_started_ns = time.perf_counter_ns()
    full_ocr_frame = preprocess_for_ocr(frame)
    preprocess_ns = time.perf_counter_ns() - preprocess_started_ns

    # 中文與英文各做一次偵測，再取聯集定位包裝；不能只依賴英文模型，
    # 否則中文藥名可能根本不在裁切範圍內。
    ocr_started_ns = time.perf_counter_ns()
    # Detection on the complete image is used only to estimate global text
    # angle.  The resulting affine transform keeps the entire canvas.
    traditional_probe = traditional_ocr.ocr(full_ocr_frame, cls=True)
    english_probe = english_ocr.ocr(full_ocr_frame, cls=True) if english_ocr else None
    probe_boxes = extract_detected_boxes(traditional_probe)
    probe_boxes.extend(extract_detected_boxes(english_probe))
    angle_fallback_roi = text_roi_bounds_from_boxes(
        frame, full_ocr_frame.shape, probe_boxes
    )
    direction_boxes = filter_boxes_by_text_angle(probe_boxes)
    estimated_angle = estimate_text_angle(direction_boxes)
    deskewed_full_image, corrected_angle = rotate_full_image_for_ocr(frame, estimated_angle)
    traditional_probe = traditional_ocr.ocr(full_ocr_frame, cls=True)
    english_probe = (
        english_ocr.ocr(full_ocr_frame, cls=True) if english_ocr else None
    )
    ocr_ns = time.perf_counter_ns() - ocr_started_ns
    preprocess_started_ns = time.perf_counter_ns()
    detected_boxes = extract_detected_boxes(traditional_probe)
    detected_boxes.extend(extract_detected_boxes(english_probe))
    direction_boxes = filter_boxes_by_text_angle(detected_boxes)
    foil_boxes = select_dominant_text_cluster(
        direction_boxes, full_ocr_frame.shape
    )
    estimated_angle = estimate_text_angle(foil_boxes)
    (
        package_roi,
        corrected_angle,
        transformed_boxes,
        roi_used,
    ) = rotate_and_extract_package_roi(
        frame,
        full_ocr_frame,
        foil_boxes,
        estimated_angle,
    )

    if not roi_used:
        corrected_angle = 0.0
        package_roi = frame.copy()
        transformed_boxes = []
    preprocess_ns += time.perf_counter_ns() - preprocess_started_ns

    ocr_started_ns = time.perf_counter_ns()
    (
        final_package_roi,
        final_ocr_frame,
        traditional_lines,
        english_lines,
        orientation,
        orientation_scores,
    ) = select_ocr_orientation(
        package_roi, traditional_ocr, english_ocr
    )
    ocr_ns += time.perf_counter_ns() - ocr_started_ns

    # Barcode branch 使用原始相機 pixels，不使用 OCR 放大或未來的 AI SR。
    barcode_started_ns = time.perf_counter_ns()
    barcode_result = run_barcode_pipeline(frame, final_package_roi, image_path, save_debug=write_outputs)
    barcode_ns = time.perf_counter_ns() - barcode_started_ns

    # 人工檢查圖一定儲存真正轉正的 package ROI，不儲存 OCR 放大圖。
    captured_text = combine_captured_text(traditional_lines, english_lines)
    inference_ms = (time.perf_counter_ns() - inference_started_ns) / 1e6
    saved_processed_path = processed_path
    if write_outputs:
        save_processed_image(processed_path, final_package_roi)
    original_height, original_width = frame.shape[:2]
    package_height, package_width = final_package_roi.shape[:2]
    ocr_height, ocr_width = final_ocr_frame.shape[:2]

    print(f"Original size       : {original_width} x {original_height}")
    print(f"ROI used            : {roi_used}")
    print(f"Deskew angle        : {corrected_angle:+.2f}°")
    print(f"Orientation         : {orientation}")
    print(f"Package ROI size    : {package_width} x {package_height}")
    print(f"OCR input size      : {ocr_width} x {ocr_height}")
    print(f"Barcode candidates  : {barcode_result['candidate_count']}")
    print(f"Barcode detected    : {len(barcode_result['barcodes'])}")

    return {
        "image": str(image_path),
        "processed_image": str(saved_processed_path),
        "barcodes": [item["text"] for item in barcode_result["barcodes"]],
        "linear_barcodes": [item["text"] for item in barcode_result["barcodes"] if item.get("format") != "QRCode"],
        "qrcodes": [item["text"] for item in barcode_result["barcodes"] if item.get("format") == "QRCode"],
        "barcode_details": barcode_result["barcodes"],
        "barcode_candidate_count": barcode_result["candidate_count"],
        "traditional_ocr": traditional_lines,
        "english_ocr": english_lines,
        "deskew_angle": corrected_angle,
        "roi_used": roi_used,
        "orientation": orientation,
        "orientation_scores": orientation_scores,
        "final_crop_width": package_width,
        "final_crop_height": package_height,
        "ocr_input_width": ocr_width,
        "ocr_input_height": ocr_height,
        "transformed_box_count": len(transformed_boxes),
        "captured_text": captured_text,
        "timing": {
            "preprocess_time_ms": round(preprocess_ns / 1e6, 2),
            "ocr_time_ms": round(ocr_ns / 1e6, 2),
            "barcode_time_ms": round(barcode_ns / 1e6, 2),
            "photo_inference_time_ms": round(inference_ms, 2),
        },
    }


def recognize_photo(
    frame,
    image_path: Path,
    processed_path: Path,
    traditional_ocr: PaddleOCR,
    english_ocr: Optional[PaddleOCR],
    write_outputs: bool = True,
) -> dict:
    """Run full-image text OCR and an independent barcode/QR pipeline."""
    inference_started_ns = time.perf_counter_ns()
    preprocess_started_ns = time.perf_counter_ns()
    # Text OCR always receives the complete image.  Orientation may rotate the
    # complete canvas, but no package/text ROI is ever extracted.
    with span("preprocess", image_path):
        full_ocr_frame = preprocess_for_ocr(frame)
    preprocess_ns = time.perf_counter_ns() - preprocess_started_ns
    ocr_started_ns = time.perf_counter_ns()
    with span("Chinese OCR probe", image_path) as event:
        event["input_shape"] = list(full_ocr_frame.shape)
        traditional_probe = traditional_ocr.ocr(full_ocr_frame, cls=True)
        event["raw_result"] = traditional_probe
    with span("English OCR probe", image_path) as event:
        event["input_shape"] = list(full_ocr_frame.shape)
        english_probe = english_ocr.ocr(full_ocr_frame, cls=True) if english_ocr else None
        event["raw_result"] = english_probe
    probe_boxes = extract_detected_boxes(traditional_probe)
    probe_boxes.extend(extract_detected_boxes(english_probe))
    angle_fallback_roi = text_roi_bounds_from_boxes(
        frame, full_ocr_frame.shape, probe_boxes
    )
    direction_boxes = filter_boxes_by_text_angle(probe_boxes)
    del traditional_probe, english_probe
    estimated_angle = estimate_text_angle(direction_boxes)
    deskewed_full_image, corrected_angle = rotate_full_image_for_ocr(frame, estimated_angle)
    (
        oriented_full_image,
        final_ocr_frame,
        traditional_lines,
        english_lines,
        orientation,
        orientation_scores,
    ) = select_ocr_orientation(deskewed_full_image, traditional_ocr, english_ocr)
    ocr_ns = time.perf_counter_ns() - ocr_started_ns
    if OCR_ORIENTATION_DEBUG:
        print(f"Photo OCR passes (including probes): {orientation_scores.get('ocr_pass_count', 0) + 1 + int(english_ocr is not None)}")

    # Barcode and QR detection own their ROI logic.  Their fallback decoders
    # also receive the original full-resolution image.
    barcode_started_ns = time.perf_counter_ns()
    try:
        with span("barcode_qr", image_path):
            barcode_result = run_barcode_pipeline(
                frame, frame, image_path, save_debug=write_outputs
            )
    except Exception as error:
        record_exception("barcode_qr", error)
        barcode_result = {"barcodes": [], "candidate_count": 0, "decode_error": str(error)}
    barcode_ns = time.perf_counter_ns() - barcode_started_ns

    captured_text = combine_captured_text(traditional_lines, english_lines)
    for item in captured_text:
        item["raw"] = item["text"]
        item["normalized"] = re.sub(
            r"[^a-z0-9\u3400-\u9fff]+", "", item["text"].casefold()
        )
        item["source"] = "full_image"
    if write_outputs:
        save_processed_image(processed_path, oriented_full_image)
    original_height, original_width = frame.shape[:2]
    ocr_height, ocr_width = final_ocr_frame.shape[:2]
    inference_ms = (time.perf_counter_ns() - inference_started_ns) / 1e6
    return {
        "image": str(image_path),
        "processed_image": str(processed_path),
        "barcodes": [item["text"] for item in barcode_result["barcodes"]],
        "qrcodes": [item["text"] for item in barcode_result["barcodes"] if "qr" in item.get("format", "").lower()],
        "barcode_details": barcode_result["barcodes"],
        "barcode_candidate_count": barcode_result["candidate_count"],
        "barcode_diagnostics": barcode_result,
        "barcode_candidates": barcode_result.get("barcode_candidates", []),
        "decoded_barcodes": barcode_result.get("decoded_barcodes", []),
        "barcode_database_matches": [],
        "traditional_ocr": traditional_lines,
        "english_ocr": english_lines,
        "deskew_angle": corrected_angle,
        "roi_used": False,
        "text_source": "full_image",
        "orientation": orientation,
        "orientation_scores": orientation_scores,
        "angle_fallback_roi": angle_fallback_roi,
        "final_crop_width": original_width,
        "final_crop_height": original_height,
        "ocr_input_width": ocr_width,
        "ocr_input_height": ocr_height,
        "transformed_box_count": 0,
        "captured_text": captured_text,
        "timing": {
            "preprocess_time_ms": round(preprocess_ns / 1e6, 2),
            "ocr_time_ms": round(ocr_ns / 1e6, 2),
            "barcode_time_ms": round(barcode_ns / 1e6, 2),
            "photo_inference_time_ms": round(inference_ms, 2),
        },
    }


def print_ocr_lines(title: str, lines: list) -> None:
    print(f"{title}：")
    if not lines:
        print("  未辨識到文字")
        return

    for line in lines:
        confidence = float(line["confidence"])
        print(f"  {confidence:6.2%}  {line['text']}")


def print_photo_result(result: dict) -> None:
    """以容易閱讀的格式輸出單張照片結果。"""
    print("\n" + "=" * 72)
    print(f"圖片：{Path(result['image']).name}")

    if "error" in result:
        print(f"錯誤：{result['error']}")
        return

    barcodes = result["barcodes"]
    print(f"處理後圖片：{result['processed_image']}")
    print(f"條碼：{' | '.join(barcodes) if barcodes else '未偵測到'}")
    print(f"ROI used: {result['roi_used']}")
    print(f"Deskew angle: {result['deskew_angle']:+.2f}°")
    print(f"Orientation: {result['orientation']}")
    print(
        f"Final crop size: {result['final_crop_width']} x "
        f"{result['final_crop_height']}"
    )
    captured_text = result.get("captured_text", [])
    print("整合辨識結果（繁體化、去除完全重複文字）：")
    if captured_text:
        for index, item in enumerate(captured_text, start=1):
            print(
                f"  {index:02d}. [{item['source']}] "
                f"{item['text']}｜{item['confidence']:.2%}"
            )
    else:
        print("  未辨識到文字")
    print(f"耗時：{result['elapsed_seconds']:.3f} 秒")


def parse_batch_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批次辨識 val/各藥品資料夾中的 cam0 + cam1 照片並產生報告。"
    )
    parser.add_argument("--val-dir", type=Path, default=DEFAULT_VAL_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--min-confidence", type=float, default=BATCH_MIN_CONFIDENCE,
        help="報告顯示及判定所需的最低 OCR 信心度（預設 0.8）。",
    )
    parser.add_argument(
        "--single-test", action="store_true",
        help="沿用舊模式，只辨識 pythonOCR/test 內的圖片。",
    )
    parser.add_argument(
        "--generate-sql", action="store_true",
        help="只讀人工修改後的 generated_drugs_review.csv 並產生 PostgreSQL SQL。",
    )
    return parser.parse_args()


def english_tokens(text: str) -> set:
    """轉成可做集合交集的英文單字；排除劑型等通用字。"""
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", text)
        if len(token) >= 3
    }
    return tokens.difference(GENERIC_ENGLISH_WORDS)


def dosage_tokens(text: str) -> set:
    """擷取並正規化劑量；5mg、5 mg、5毫克都會變成 ``5mg``。"""
    normalized = to_traditional_chinese(text).lower()
    normalized = normalized.replace("毫克", "mg").replace("微克", "mcg")
    normalized = normalized.replace("公克", "g")
    matches = re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mcg|ug|mg|g)(?![a-z])",
        normalized,
    )
    tokens = set()
    for number, unit in matches:
        unit = "mcg" if unit == "ug" else unit
        # 5.0mg 與 5mg 應視為同一劑量。
        canonical_number = format(float(number), "g")
        tokens.add(f"{canonical_number}{unit}")
    return tokens


def normalize_strength(text: str) -> str:
    """Return one canonical strength such as 66.7mg, 100mcg or 1g."""
    strengths = sorted(dosage_tokens(text))
    return strengths[0] if strengths else ""


def parse_folder_metadata(folder_name: str) -> dict:
    """Parse authoritative English name, strength and dosage form from folder."""
    strength = normalize_strength(folder_name)
    working = re.sub(
        r"(?<![\d.])\d+(?:\.\d+)?\s*(?:mcg|ug|mg|g)(?![a-z])",
        " ",
        folder_name,
        flags=re.IGNORECASE,
    )
    dosage_form = ""
    for form in DOSAGE_FORMS:
        match = re.search(
            rf"(?<![A-Za-z]){re.escape(form)}(?![A-Za-z])",
            working,
            flags=re.IGNORECASE,
        )
        if match:
            dosage_form = working[match.start():match.end()].strip()
            working = working[:match.start()] + " " + working[match.end():]
            break
    drug_name_en = re.sub(r"\s+", " ", working).strip(" -_/.,")
    return {
        "drug_name_en": drug_name_en,
        "strength": strength,
        "dosage_form_en": dosage_form,
        "dosage_form_zh": DOSAGE_FORM_ZH.get(dosage_form.lower(), ""),
    }


def normalize_ocr_text(text: str) -> str:
    text = to_traditional_chinese(str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalized_consensus_key(text: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text.lower())


def group_similar_ocr_texts(evidence: list, similarity: float = 0.82) -> list:
    """Cluster OCR candidates without inventing corrections or translations."""
    groups = []
    for item in evidence:
        key = _normalized_consensus_key(item["text"])
        if not key:
            continue
        best_group = None
        best_ratio = 0.0
        for group in groups:
            ratio = difflib.SequenceMatcher(None, key, group["key"]).ratio()
            if ratio >= similarity and ratio > best_ratio:
                best_group, best_ratio = group, ratio
        if best_group is None:
            groups.append({"key": key, "items": [item]})
        else:
            best_group["items"].append(item)
    return groups


def choose_consensus_text(
    evidence: list,
    similarity: float = 0.82,
    min_images: int = 2,
    min_confidence: float = 0.80,
) -> tuple:
    """Return (value, conflict) using cross-image support and confidence."""
    groups = group_similar_ocr_texts(evidence, similarity)
    qualified = []
    for group in groups:
        images = {item["image"] for item in group["items"]}
        max_confidence = max(
            (float(item["confidence"]) for item in group["items"]), default=0.0
        )
        if len(images) < min_images or max_confidence < min_confidence:
            continue
        exact = defaultdict(list)
        for item in group["items"]:
            exact[_normalized_consensus_key(item["text"])].append(item)
        representative_items = max(
            exact.values(),
            key=lambda items: (
                len({item["image"] for item in items}),
                len(items),
                max(float(item["confidence"]) for item in items),
            ),
        )
        representative = max(
            representative_items, key=lambda item: float(item["confidence"])
        )["text"]
        qualified.append((len(images), len(group["items"]), max_confidence, representative))
    qualified.sort(reverse=True)
    if not qualified:
        return "", bool(evidence)
    if len(qualified) > 1 and qualified[0][:2] == qualified[1][:2]:
        return "", True
    return qualified[0][3], len(qualified) > 1


def _evidence_item(text: str, image: str, confidence: float, source: str) -> dict:
    return {
        "text": normalize_ocr_text(text),
        "image": image,
        "confidence": float(confidence),
        "source": source,
    }


def _format_evidence(items: list) -> str:
    output, seen = [], set()
    for item in sorted(
        items,
        key=lambda value: (value["image"], -float(value["confidence"]), value["text"]),
    ):
        key = (item["text"], item["image"], round(float(item["confidence"]), 4))
        if key in seen:
            continue
        seen.add(key)
        output.append(
            f"{item['text']} [{item['image']}, {float(item['confidence']):.2%}]"
        )
    return " | ".join(output)


def collect_drug_evidence(class_name: str, rows: list) -> dict:
    """Collect conservative database evidence from every image in one folder."""
    metadata = parse_folder_metadata(class_name)
    evidence = defaultdict(list)
    decoded_barcodes = []
    from drug_matching.identifiers import decoded_evidence
    from drug_matching.license_extractor import extract_licenses
    folder_key = _normalized_consensus_key(metadata["drug_name_en"])
    manufacturer_pattern = re.compile(
        r"(?:製藥|藥廠|藥品|生技|pharma(?:ceutical)?|laborator(?:y|ies)|company|co\.?\s*,?\s*ltd)",
        re.IGNORECASE,
    )
    generic_words = {
        "tablet", "tablets", "tab", "tabs", "capsule", "capsules",
        "granules", "effervescent", "chewable", "film", "coated",
        "extended", "release", "mg", "mcg",
    }

    for result in rows:
        image = Path(result.get("image", "unknown")).stem
        for item in decoded_evidence(result.get("barcode_details", [])):
            value = item['normalized_value']
            decoded_barcodes.append(value)
            evidence["barcode"].append(_evidence_item(value, image, 1.0, "BARCODE_DECODED"))
        for captured in result.get("captured_text", []):
            text = normalize_ocr_text(captured.get("text", ""))
            if not text:
                continue
            confidence = float(captured.get("confidence", 0.0))
            source = str(captured.get("source", "OCR"))
            base = _evidence_item(text, image, confidence, source)

            for strength in dosage_tokens(text):
                evidence["strength"].append(
                    _evidence_item(strength, image, confidence, source)
                )

            for number in re.findall(r"(?<!\d)\d{8,14}(?!\d)", text):
                evidence["ocr_number"].append(
                    _evidence_item(number, image, confidence, "OCR_NUMBER")
                )

            for licence in extract_licenses([text]):
                value = f"藥{licence['kind']}字第{licence['number']}號"
                evidence["license_number"].append(
                    _evidence_item(value, image, confidence, "LICENSE_OCR")
                )

            if manufacturer_pattern.search(text):
                evidence["manufacturer"].append(base)

            chinese_runs = re.findall(r"[\u3400-\u9fff]{2,20}", text)
            is_parenthesized = bool(re.search(r"[（(].*[\u3400-\u9fff].*[）)]", text))
            for run in chinese_runs:
                item = _evidence_item(run, image, confidence, source)
                if is_parenthesized:
                    evidence["ingredient_zh"].append(item)
                elif not manufacturer_pattern.search(run) and not re.search(
                    r"(?:許可|字第|毫克|成分|每錠)", run
                ):
                    evidence["drug_name_zh"].append(item)

            english_chunks = re.findall(r"[A-Za-z][A-Za-z .'-]{3,60}", text)
            for chunk in english_chunks:
                chunk = re.sub(r"\s+", " ", chunk).strip(" .'-")
                words = {word.lower() for word in re.findall(r"[A-Za-z]+", chunk)}
                if not chunk or words.issubset(generic_words):
                    continue
                item = _evidence_item(chunk, image, confidence, source)
                chunk_key = _normalized_consensus_key(chunk)
                if folder_key and difflib.SequenceMatcher(
                    None, chunk_key, folder_key
                ).ratio() >= 0.72:
                    evidence["drug_name_en"].append(item)
                elif not manufacturer_pattern.search(chunk) and len(chunk_key) >= 5:
                    evidence["ingredient_en"].append(item)

    evidence["decoded_barcodes"] = sorted(set(filter(None, decoded_barcodes)))
    return evidence


def choose_chinese_drug_name(evidence: list) -> tuple:
    return choose_consensus_text(evidence, similarity=0.74)


def choose_ingredient_en(evidence: list) -> tuple:
    return choose_consensus_text(evidence, similarity=0.84)


def choose_ingredient_zh(evidence: list) -> tuple:
    return choose_consensus_text(evidence, similarity=0.78)


def choose_license_number(evidence: list) -> tuple:
    return choose_consensus_text(evidence, similarity=1.0)


def choose_barcode(decoded_values: list) -> tuple:
    values = sorted(set(filter(None, decoded_values)))
    return (values[0], False) if len(values) == 1 else ("", len(values) > 1)


def build_drug_record(class_name: str, image_results: list) -> dict:
    metadata = parse_folder_metadata(class_name)
    evidence = collect_drug_evidence(class_name, image_results)
    drug_name_zh, drug_zh_conflict = choose_chinese_drug_name(
        evidence["drug_name_zh"]
    )
    ingredient_en, ingredient_en_conflict = choose_ingredient_en(
        evidence["ingredient_en"]
    )
    ingredient_zh, ingredient_zh_conflict = choose_ingredient_zh(
        evidence["ingredient_zh"]
    )
    license_number, license_conflict = choose_license_number(
        evidence["license_number"]
    )
    manufacturer, _ = choose_consensus_text(
        evidence["manufacturer"], similarity=0.82
    )
    barcode, barcode_conflict = choose_barcode(evidence["decoded_barcodes"])
    warnings = []
    if not drug_name_zh:
        warnings.append("no reliable Chinese drug name")
    if not ingredient_en and evidence["ingredient_en"]:
        warnings.append("ingredient English conflict")
    if not ingredient_zh and evidence["ingredient_zh"]:
        warnings.append("ingredient Chinese conflict")
    if license_conflict:
        warnings.append("license number conflict")
    if barcode_conflict:
        warnings.append("multiple barcode values detected")
    elif not barcode:
        warnings.append("no barcode decoded")
    if not manufacturer:
        warnings.append("manufacturer unavailable")
    if not any(result.get("captured_text") for result in image_results):
        warnings.append("insufficient OCR evidence")
    return {
        "folder_name": class_name,
        "drug_name_en": metadata["drug_name_en"],
        "drug_name_zh": drug_name_zh,
        "ingredient_en": ingredient_en,
        "ingredient_zh": ingredient_zh,
        "strength": metadata["strength"],
        "dosage_form_en": metadata["dosage_form_en"],
        "dosage_form_zh": metadata["dosage_form_zh"],
        "license_number": license_number,
        "barcode": barcode,
        "manufacturer": manufacturer,
        "drug_name_en_evidence": _format_evidence(evidence["drug_name_en"]),
        "drug_name_zh_evidence": _format_evidence(evidence["drug_name_zh"]),
        "ingredient_en_evidence": _format_evidence(evidence["ingredient_en"]),
        "ingredient_zh_evidence": _format_evidence(evidence["ingredient_zh"]),
        "strength_evidence": _format_evidence(evidence["strength"]),
        "license_number_evidence": _format_evidence(evidence["license_number"]),
        "barcode_evidence": _format_evidence(evidence["barcode"]),
        "manufacturer_evidence": _format_evidence(evidence["manufacturer"]),
        "warning": " | ".join(dict.fromkeys(warnings)),
    }


def build_dataset_text(
    english_text: str,
    chinese_intersections: list,
    chinese_text: str,
    recognized_dosages: set,
) -> str:
    """Build a dataset label exclusively from high-confidence OCR evidence."""
    dataset_english = english_text.strip() or "辨識不到（需人工補登）"
    consensus_texts = []
    for item in chinese_intersections:
        text = to_traditional_chinese(str(item.get("text", ""))).strip()
        if text and text not in consensus_texts:
            consensus_texts.append(text)
    dataset_chinese = " | ".join(consensus_texts) or chinese_text.strip()
    if not dataset_chinese:
        dataset_chinese = "辨識不到（需人工補登）"
    dosage_text = (
        " | ".join(sorted(recognized_dosages))
        or "辨識不到（需人工補登）"
    )
    return (
        f"英文：{dataset_english}；"
        f"中文：{dataset_chinese}；"
        f"劑量：{dosage_text}"
    )


def chinese_consensus(items: list, min_length: int = 2) -> list:
    """找出高信心度中文結果的共同連續字串，保留順序而非打散成字元集合。

    例如「愛舒疼健」和「愛舒疼錠」的交集會輸出「愛舒疼」，不會把字序
    打亂。每個交集同時保留支持筆數及支持證據中的最低信心度。
    """
    evidence = []
    for item in items:
        runs = re.findall(r"[\u3400-\u9fff]+", to_traditional_chinese(item["text"]))
        for run in runs:
            if len(run) >= min_length:
                evidence.append((run, float(item["confidence"])))

    if not evidence:
        return []
    if len(evidence) == 1:
        text, confidence = evidence[0]
        return [{"text": text, "support": 1, "confidence": confidence}]

    candidates = set()
    for text, _ in evidence:
        for length in range(min_length, len(text) + 1):
            candidates.update(
                text[index:index + length]
                for index in range(len(text) - length + 1)
            )

    consensus = []
    for candidate in candidates:
        supporters = [confidence for text, confidence in evidence if candidate in text]
        if len(supporters) >= 2:
            consensus.append({
                "text": candidate,
                "support": len(supporters),
                "confidence": min(supporters),
            })

    # 優先支持筆數，再取較長字串；移除已被更完整結果包含的短片段。
    consensus.sort(
        key=lambda item: (item["support"], len(item["text"]), item["confidence"]),
        reverse=True,
    )
    selected = []
    for item in consensus:
        if any(
            item["text"] in existing["text"]
            and item["support"] <= existing["support"]
            for existing in selected
        ):
            continue
        selected.append(item)
    return selected


def high_confidence_content(result: dict, threshold: float) -> dict:
    """只留下達門檻內容，並分成英文與中文供自動/人工核對。"""
    accepted = [
        item for item in result.get("captured_text", [])
        if float(item["confidence"]) >= threshold
    ]
    english = [item for item in accepted if re.search(r"[A-Za-z]", item["text"])]
    chinese = [item for item in accepted if re.search(r"[\u3400-\u9fff]", item["text"])]
    return {"all": accepted, "english": english, "chinese": chinese}


def text_side_score(result: dict, threshold: float) -> tuple:
    """分數越高越像文字面；pair 中分數較低的一張視為藥丸面。"""
    content = high_confidence_content(result, threshold)
    accepted = content["all"]
    all_lines = result.get("traditional_ocr", []) + result.get("english_ocr", [])
    return (
        len(accepted),
        sum(float(item["confidence"]) for item in accepted),
        len(all_lines),
        sum(float(item["confidence"]) for item in all_lines),
    )


def find_validation_pairs(val_dir: Path) -> list:
    """依英文藥品資料夾及六位數編號收集 cam0/cam1 配對。"""
    if not val_dir.is_dir():
        raise FileNotFoundError(f"找不到驗證資料夾：{val_dir}")
    pairs = []
    for class_dir in sorted((p for p in val_dir.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        groups = defaultdict(dict)
        for path in class_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            match = PAIR_PATTERN.fullmatch(path.stem)
            if match:
                groups[match.group(1)][f"cam{match.group(2)}"] = path
        for group_id in sorted(groups):
            cameras = groups[group_id]
            pairs.append({
                "class": class_dir.name,
                "group_id": group_id,
                "cam0": cameras.get("cam0"),
                "cam1": cameras.get("cam1"),
            })
    return pairs


def write_csv(path: Path, fieldnames: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_drug_review_csv(report_dir: Path, records: list) -> Path:
    """Write the single human-review table (one folder, one record)."""
    review_path = report_dir / DRUG_REVIEW_FILENAME
    readable_records = []
    for record in records:
        readable = dict(record)
        for field in DRUG_REVIEW_EDITABLE_FIELDS:
            current_value = str(readable.get(field, "")).strip()
            if not current_value or current_value == DRUG_REVIEW_EMPTY_VALUE:
                readable[field] = DRUG_REVIEW_FIELD_PROMPTS[field]
        for field in DRUG_REVIEW_EVIDENCE_FIELDS:
            if not str(readable.get(field, "")).strip():
                readable[field] = DRUG_REVIEW_NO_EVIDENCE
        if not str(readable.get("warning", "")).strip():
            readable["warning"] = DRUG_REVIEW_NO_WARNING
        readable_records.append(readable)
    write_csv(review_path, DRUG_REVIEW_FIELDS, readable_records)
    return review_path


def rebuild_drug_review_from_detail_csv(detail_path: Path, report_dir: Path):
    """Recover the review table from the existing high-confidence detail CSV."""
    with detail_path.open("r", newline="", encoding="utf-8-sig") as file:
        detail_rows = list(csv.DictReader(file))
    grouped_results = defaultdict(list)
    for row in detail_rows:
        folder_name = str(row.get("藥品資料夾", "")).strip()
        if not folder_name:
            continue
        captured_text = []
        for column, source in (
            ("英文OCR_信心度至少0.8", "英文模型"),
            ("中文OCR_人工核對", "中文模型"),
        ):
            for text in str(row.get(column, "")).split(" | "):
                text = text.strip()
                if text:
                    captured_text.append({
                        "text": text,
                        "confidence": BATCH_MIN_CONFIDENCE,
                        "source": source,
                    })
        barcodes = [
            value.strip()
            for value in str(row.get("條碼內容", "")).split(" | ")
            if value.strip()
        ]
        grouped_results[folder_name].append({
            "image": str(row.get("檔案", "")),
            "captured_text": captured_text,
            "barcodes": barcodes,
            # Legacy CSV strings lack decoder provenance and remain display-only.
            "barcode_details": json.loads(row.get("條碼解碼證據JSON") or "[]"),
        })
    records = [
        build_drug_record(folder_name, grouped_results[folder_name])
        for folder_name in sorted(grouped_results, key=str.lower)
    ]
    return write_drug_review_csv(report_dir, records), records


def sql_literal(value) -> str:
    if value is None or str(value).strip() in {
        "", DRUG_REVIEW_EMPTY_VALUE, *DRUG_REVIEW_FIELD_PROMPTS.values()
    }:
        return "NULL"
    return "'" + str(value).strip().replace("'", "''") + "'"


def generate_sql_from_review_csv(review_path: Path, sql_path: Path) -> int:
    """Generate PostgreSQL using only the current, possibly edited review CSV."""
    review_path = review_path.resolve()
    if not review_path.is_file():
        raise FileNotFoundError(f"找不到人工檢查總表：{review_path}")
    with review_path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {
            "drug_name_en", "drug_name_zh", "ingredient_en", "ingredient_zh",
            "strength", "dosage_form_en", "dosage_form_zh", "license_number",
            "barcode", "manufacturer",
        }
        missing = sorted(required.difference(reader.fieldnames or []))
        if missing:
            raise ValueError(f"review CSV 缺少欄位：{', '.join(missing)}")
        rows = list(reader)

    lines = [
        "BEGIN;", "", "CREATE TABLE IF NOT EXISTS drugs (",
        "    id SERIAL PRIMARY KEY,", "",
        "    drug_name_en VARCHAR(150),", "    drug_name_zh VARCHAR(150),", "",
        "    ingredient_en VARCHAR(250),", "    ingredient_zh VARCHAR(250),", "",
        "    strength VARCHAR(50),", "    dosage_form_en VARCHAR(100),",
        "    dosage_form_zh VARCHAR(100),", "",
        "    license_number VARCHAR(50),", "    barcode VARCHAR(100),", "",
        "    manufacturer VARCHAR(150),", "",
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP", ");", "",
        "ALTER TABLE drugs ADD COLUMN IF NOT EXISTS dosage_form_en VARCHAR(100);",
        "ALTER TABLE drugs ADD COLUMN IF NOT EXISTS dosage_form_zh VARCHAR(100);", "",
    ]
    columns = [
        "drug_name_en", "drug_name_zh", "ingredient_en", "ingredient_zh",
        "strength", "dosage_form_en", "dosage_form_zh", "license_number",
        "barcode", "manufacturer",
    ]
    for index, row in enumerate(rows, start=1):
        folder = str(row.get("folder_name", "")).replace("\r", " ").replace("\n", " ")
        values = [sql_literal(row.get(column)) for column in columns]
        lines.extend([
            f"-- Drug {index}: {folder}",
            "INSERT INTO drugs (",
            "    drug_name_en, drug_name_zh, ingredient_en, ingredient_zh,",
            "    strength, dosage_form_en, dosage_form_zh, license_number,",
            "    barcode, manufacturer",
            ")",
            "SELECT",
            "    " + ", ".join(values),
            "WHERE NOT EXISTS (",
            "    SELECT 1",
            "    FROM drugs",
            f"    WHERE drug_name_en IS NOT DISTINCT FROM {values[0]}",
            f"      AND strength IS NOT DISTINCT FROM {values[4]}",
            f"      AND dosage_form_en IS NOT DISTINCT FROM {values[5]}",
            ");", "",
        ])
    lines.extend(["COMMIT;", ""])
    sql_path = sql_path.resolve()
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text("\n".join(lines), encoding="utf-8")
    return len(rows)


def build_class_summary(detail_rows: list) -> list:
    """由目前已完成的逐張資料建立各藥品摘要。"""
    summaries = []
    class_names = sorted({row["藥品資料夾"] for row in detail_rows}, key=str.lower)
    for class_name in class_names:
        rows = [row for row in detail_rows if row["藥品資料夾"] == class_name]
        unrecognized = [row for row in rows if row["核對狀態"] == "辨識不到"]
        wrong = [row for row in rows if row["核對狀態"] == "辨識錯誤"]
        correct = [row for row in rows if row["核對狀態"] == "正確"]
        summaries.append({
            "藥品資料夾": class_name,
            "配對數": len({row["照片編號"] for row in rows}),
            "正確數": len(correct),
            "辨識不到數": len(unrecognized),
            "辨識不到照片編號": " | ".join(
                f"{row['照片編號']}_{row['相機']}" for row in unrecognized
            ),
            "辨識錯誤數": len(wrong),
            "辨識錯誤照片編號": " | ".join(
                f"{row['照片編號']}_{row['相機']}" for row in wrong
            ),
        })
    return summaries


def save_validation_checkpoint(report_dir: Path, detail_rows: list, class_name: str):
    """每完成一個藥品資料夾，立即保存個別報告及累積總報告。"""
    if not detail_rows:
        return None, None, None
    class_rows = [row for row in detail_rows if row["藥品資料夾"] == class_name]
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", class_name).strip(" .") or "unknown"
    class_path = report_dir / "class_reports" / f"{safe_name}.csv"
    detail_path = report_dir / "ocr_detail_report.csv"
    summary_path = report_dir / "ocr_class_summary.csv"
    summaries = build_class_summary(detail_rows)
    write_csv(class_path, list(class_rows[0].keys()), class_rows)
    write_csv(detail_path, list(detail_rows[0].keys()), detail_rows)
    write_csv(summary_path, list(summaries[0].keys()), summaries)
    return class_path, detail_path, summary_path


def failed_recognition_result(image_path: Path, error: Exception) -> dict:
    """Return a report-compatible empty result so one bad image cannot stop val."""
    return {
        "image": str(image_path),
        "processed_image": "",
        "barcodes": [],
        "barcode_details": [],
        "barcode_candidate_count": 0,
        "traditional_ocr": [],
        "english_ocr": [],
        "deskew_angle": 0.0,
        "roi_used": False,
        "orientation": "ERROR",
        "orientation_scores": {},
        "final_crop_width": 0,
        "final_crop_height": 0,
        "ocr_input_width": 0,
        "ocr_input_height": 0,
        "transformed_box_count": 0,
        "captured_text": [],
        "error": f"{type(error).__name__}: {error}",
        **exception_details(error),
    }


def evaluate_validation(args: argparse.Namespace) -> None:
    if not 0.0 <= args.min_confidence <= 1.0:
        raise ValueError("--min-confidence 必須介於 0 和 1。")
    val_dir = args.val_dir.resolve()
    report_dir = args.report_dir.resolve()
    folder_names = sorted(
        (path.name for path in val_dir.iterdir() if path.is_dir()),
        key=str.lower,
    ) if val_dir.is_dir() else []
    drug_results = {folder_name: [] for folder_name in folder_names}
    pairs = find_validation_pairs(val_dir)
    if not pairs:
        raise FileNotFoundError(f"{val_dir} 中沒有可辨識的 cam0/cam1 照片。")

    traditional_ocr, english_ocr = load_ocr_engines()
    detail_rows = []
    missing_pairs = []
    started = time.perf_counter()
    print(f"找到 {len(pairs)} 組照片，信心度門檻：{args.min_confidence:.0%}")

    for pair_index, pair in enumerate(pairs, start=1):
        class_name = pair["class"]
        group_id = pair["group_id"]
        print(f"[{pair_index}/{len(pairs)}] {class_name} / {group_id}")
        if pair["cam0"] is None or pair["cam1"] is None:
            missing_pairs.append(f"{class_name}/{group_id}")
            next_class = pairs[pair_index]["class"] if pair_index < len(pairs) else None
            if next_class != class_name and any(
                row["藥品資料夾"] == class_name for row in detail_rows
            ):
                class_path, _, _ = save_validation_checkpoint(
                    report_dir, detail_rows, class_name
                )
                print(f"資料集報告已儲存：{class_path}")
            continue

        results = {}
        for camera in ("cam0", "cam1"):
            path = pair[camera]
            processed_path = report_dir / "processed" / class_name / f"{path.stem}.png"
            try:
                frame, resolved = read_image(path)
                results[camera] = recognize_photo(
                    frame, resolved, processed_path, traditional_ocr, english_ocr
                )
            except Exception as error:
                results[camera] = failed_recognition_result(path, error)
                print(
                    f"ERROR: {class_name}/{path.name} failed: "
                    f"{type(error).__name__}: {error}"
                )
                print("The failed image is recorded as unrecognized; batch continues.")
            drug_results.setdefault(class_name, []).append(results[camera])

        # 題目保證一組中必有一張藥丸面，因此 OCR 證據較少者標成藥丸。
        pill_camera = min(
            ("cam0", "cam1"),
            key=lambda camera: text_side_score(
                results[camera], args.min_confidence
            ),
        )
        expected_tokens = english_tokens(class_name)
        expected_dosages = dosage_tokens(class_name)

        for camera in ("cam0", "cam1"):
            result = results[camera]
            path = pair[camera]
            content = high_confidence_content(result, args.min_confidence)
            english_text = " | ".join(item["text"] for item in content["english"])
            chinese_text = " | ".join(item["text"] for item in content["chinese"])
            chinese_intersections = chinese_consensus(content["chinese"])
            chinese_intersection_text = " | ".join(
                f"{item['text']} (支持{item['support']}筆，最低信心度"
                f"{item['confidence']:.2%})"
                for item in chinese_intersections
            )
            recognized_tokens = set().union(
                *(english_tokens(item["text"]) for item in content["english"])
            ) if content["english"] else set()
            intersection = expected_tokens.intersection(recognized_tokens)
            recognized_dosages = dosage_tokens(
                " | ".join(item["text"] for item in content["all"])
            )
            dataset_text = build_dataset_text(
                english_text,
                chinese_intersections,
                chinese_text,
                recognized_dosages,
            )
            # 資料夾有標示劑量時必須全部吻合；例如 5mg 不能因藥名相同
            # 而誤判成 10mg。資料夾沒有劑量時則不啟用此限制。
            dosage_match = (
                not expected_dosages
                or expected_dosages.issubset(recognized_dosages)
            )

            if result.get("error"):
                output = "辨識不到"
                status = "辨識不到"
            elif camera == pill_camera:
                output = "藥丸"
                status = "藥丸"
            elif not content["all"]:
                output = "辨識不到"
                status = "辨識不到"
            elif intersection and dosage_match:
                output = english_text or chinese_text
                status = "正確"
            else:
                output = english_text or chinese_text
                status = "辨識錯誤"

            detail_rows.append({
                "藥品資料夾": class_name,
                "照片編號": group_id,
                "相機": camera,
                "檔案": path.name,
                "判定": output,
                "核對狀態": status,
                "dataset文字": dataset_text,
                "英文OCR_信心度至少0.8": english_text,
                "中文OCR_人工核對": chinese_text,
                "中文OCR_高信心度交集": chinese_intersection_text,
                "資料夾英文詞": " | ".join(sorted(expected_tokens)),
                "英文交集": " | ".join(sorted(intersection)),
                "預期劑量": " | ".join(sorted(expected_dosages)),
                "辨識劑量": " | ".join(sorted(recognized_dosages)),
                "劑量相符": "是" if dosage_match else "否",
                "ROI_used": result["roi_used"],
                "校正角度": f"{result['deskew_angle']:.2f}",
                "最終方向": result["orientation"],
                "最終裁切尺寸": (
                    f"{result['final_crop_width']}x{result['final_crop_height']}"
                ),
                "OCR輸入尺寸": (
                    f"{result['ocr_input_width']}x{result['ocr_input_height']}"
                ),
                "條碼候選數": result["barcode_candidate_count"],
                "條碼解碼數": len(result["barcodes"]),
                "條碼內容": " | ".join(result["barcodes"]),
                "條碼解碼證據JSON": json.dumps(result.get("barcode_details", []), ensure_ascii=False),
                "處理後圖片": result["processed_image"],
            })

        next_class = pairs[pair_index]["class"] if pair_index < len(pairs) else None
        if next_class != class_name:
            class_path, detail_path, summary_path = save_validation_checkpoint(
                report_dir, detail_rows, class_name
            )
            print(f"資料集報告已儲存：{class_path}")

    # 最後一個資料集在上方已完成 checkpoint；這裡只取得固定總報告路徑。
    detail_path = report_dir / "ocr_detail_report.csv"
    summary_path = report_dir / "ocr_class_summary.csv"
    elapsed = time.perf_counter() - started
    print(f"完成，耗時 {elapsed:.2f} 秒")
    print(f"逐張明細：{detail_path}")
    print(f"各藥品統計：{summary_path}")
    if missing_pairs:
        print(f"缺少正反面配對：{', '.join(missing_pairs)}")

    drug_records = [
        build_drug_record(folder_name, drug_results.get(folder_name, []))
        for folder_name in folder_names
    ]
    review_path = write_drug_review_csv(report_dir, drug_records)
    warning_count = sum(bool(record["warning"]) for record in drug_records)
    print("=" * 60)
    print("Drug review generation")
    print("=" * 60)
    print(f"Drug folders       : {len(folder_names)}")
    print(f"Generated records  : {len(drug_records)}")
    print(f"Warnings           : {warning_count}")
    print("Review CSV         :")
    print(review_path)
    if len(folder_names) != len(drug_records):
        print("WARNING: folder count does not match review record count")
    print("=" * 60)


def run_single_test() -> None:
    # Windows 傳統 cp950 主控台無法輸出 emoji；強制 UTF-8 避免程式尚未 OCR 就中止。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    image_paths = find_test_images(TEST_DIR)
    print(f"🖼️ 找到 {len(image_paths)} 張照片：{TEST_DIR}")

    # 全部照片共用同一組模型，不會每張重新載入。
    traditional_ocr, english_ocr = load_ocr_engines()
    total_started_at = time.perf_counter()
    results = []

    for index, image_path in enumerate(image_paths, start=1):
        relative_path = image_path.relative_to(TEST_DIR.resolve())
        print(f"🔎 [{index}/{len(image_paths)}] {relative_path}")
        image_started_at = time.perf_counter()
        processed_path = (
            PROCESSED_DIR
            / relative_path.parent
            / f"{relative_path.stem}_ocr_input.png"
        )

        try:
            frame, resolved_path = read_image(image_path)
            image_result = recognize_photo(
                frame,
                resolved_path,
                processed_path,
                traditional_ocr,
                english_ocr,
            )
            image_result["elapsed_seconds"] = round(
                time.perf_counter() - image_started_at,
                3,
            )
        except Exception as error:
            # 單張損壞不會中止其他照片的辨識。
            image_result = {
                "image": str(image_path),
                "error": f"{type(error).__name__}: {error}",
        **exception_details(error),
            }

        results.append(image_result)
        print_photo_result(image_result)

    total_elapsed = time.perf_counter() - total_started_at
    failed_count = sum("error" in result for result in results)
    print("\n" + "=" * 72)
    print(
        f"完成：{len(results)} 張｜成功 {len(results) - failed_count} 張｜"
        f"失敗 {failed_count} 張｜總耗時 {total_elapsed:.3f} 秒"
    )


def main() -> None:
    # Windows 傳統 cp950 主控台無法輸出 emoji；強制 UTF-8 避免程式尚未 OCR 就中止。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_batch_args()
    if args.generate_sql:
        review_path = args.report_dir.resolve() / DRUG_REVIEW_FILENAME
        sql_path = args.report_dir.resolve() / DRUG_SQL_FILENAME
        record_count = generate_sql_from_review_csv(review_path, sql_path)
        print("=" * 60)
        print("SQL generation")
        print("=" * 60)
        print(f"Review records     : {record_count}")
        print(f"Generated records  : {record_count}")
        print("SQL file           :")
        print(sql_path)
        print("=" * 60)
    elif args.single_test:
        run_single_test()
    else:
        evaluate_validation(args)


if __name__ == "__main__":
    main()
