"""Resource samples; unavailable GPU metrics remain null, never fake zeros."""
import subprocess
import sys
import traceback

import psutil


class ResourceMonitor:
    def __init__(self, use_gpu=False):
        self.process = psutil.Process()
        self.process.cpu_percent()
        psutil.cpu_percent()
        self.use_gpu = use_gpu

    def sample(self):
        row = {"process_ram_mb": round(self.process.memory_info().rss / 1048576, 2),
               "system_ram_percent": psutil.virtual_memory().percent,
               "thread_count": self.process.num_threads(),
               "process_cpu_percent": self.process.cpu_percent(),
               "system_cpu_percent": psutil.cpu_percent(),
               "gpu_vram_mb": None, "gpu_vram_reserved_mb": None,
               "gpu_utilization_percent": None, "gpu_device_used_mb": None,
               "monitor_error": ""}
        if not self.use_gpu:
            return row
        try:
            paddle = sys.modules.get("paddle")
            row["gpu_vram_mb"] = paddle.device.cuda.memory_allocated() / 1048576
            row["gpu_vram_reserved_mb"] = paddle.device.cuda.memory_reserved() / 1048576
        except Exception as error:
            row["monitor_error"] = "Paddle allocator: " + traceback.format_exc()
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # Device-level metrics, including other processes; retain every GPU.
            row["gpu_device_used_mb"] = output.stdout.strip().replace("\n", " | ")
            row["gpu_utilization_percent"] = " | ".join(line.split(",")[-1].strip() for line in output.stdout.splitlines())
        except Exception as error:
            row["monitor_error"] += "; nvidia-smi: " + traceback.format_exc()
        return row


def pass_times(result):
    events = result.get("diagnostics", {}).get("events", [])
    def total(prefix):
        return round(sum(e.get("elapsed_ms", 0) for e in events if e["stage"].startswith(prefix)) / 1000, 6)
    return {"english_0_time": total("English OCR 0"),
            "english_180_time": total("English OCR 180"),
            "english_probe_time": total("English OCR probe"),
            "chinese_time": total("Chinese OCR"),
            "ocr_pass_count": sum(" OCR " in e["stage"] for e in events),
            "ocr_total_time": total("English OCR") + total("Chinese OCR")}
