import english from "./locales/en.json";

export type Language = "zh-Hant" | "en";
const messages: Record<string, string> = english;

// Presentation only: source prescription names, matching keys, API payloads and
// filter values remain unchanged when the user switches languages.
export function translate<T>(value: T, language: Language): T {
  if (language !== "en" || typeof value !== "string") return value;
  const trimmed = value.trim();
  let translated = messages[trimmed];
  if (!translated) {
    const patterns: [RegExp, (...parts: string[]) => string][] = [
      [/^下載全部 ZIP（(\d+) 張）$/, n => `Download all ZIP (${n} photos)`],
      [/^確定清除暫存清單中的 (\d+) 組照片嗎？$/, n => `Clear all ${n} capture sets from the buffer?`],
      [/^Camera (\d+) 即時預覽$/, n => `Camera ${n} live preview`],
      [/^Camera (\d+) 拍攝結果$/, n => `Camera ${n} capture result`],
      [/^第 (\d+) 組 Camera (\d+)$/, (set, camera) => `Set ${set}, Camera ${camera}`],
      [/^刪除第 (\d+) 組 Camera (\d+) 照片$/, (set, camera) => `Delete Camera ${camera} photo from set ${set}`],
      [/^刪除第 (\d+) 組照片$/, n => `Delete capture set ${n}`],
      [/^無法取得(上鏡頭|下鏡頭)照片$/, camera => `Could not retrieve the ${camera === "上鏡頭" ? "top" : "bottom"} camera photo`],
      [/^第 (\d+) 項藥品格式不正確$/, n => `Medicine ${n} has an invalid format`],
      [/^第 (\d+) 項藥品缺少 name$/, n => `Medicine ${n} is missing its name`],
    ];
    for (const [pattern, format] of patterns) {
      const match = trimmed.match(pattern);
      if (match) { translated = format(...match.slice(1)); break; }
    }
  }
  if (!translated) return value;
  return `${value.slice(0, value.length - value.trimStart().length)}${translated}${value.slice(value.trimEnd().length)}` as T;
}
