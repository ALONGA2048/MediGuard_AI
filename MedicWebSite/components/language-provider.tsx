"use client";

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";
import { Languages } from "lucide-react";
import { translate, type Language } from "@/lib/i18n";

const preferenceKey = "mediguard-language";
const changeEvent = "mediguard-language-change";
let currentLanguage: Language = "zh-Hant";
function snapshot(): Language {
  try {
    const saved = window.localStorage.getItem(preferenceKey);
    if (saved === "en" || saved === "zh-Hant") return saved;
  } catch { /* The language still works when browser storage is unavailable. */ }
  return currentLanguage;
}
function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(changeEvent, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(changeEvent, listener);
  };
}
const LanguageContext = createContext<{ language: Language; toggle: () => void } | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const language = useSyncExternalStore<Language>(subscribe, snapshot, () => "zh-Hant");
  const toggle = useCallback(() => {
    currentLanguage = snapshot() === "en" ? "zh-Hant" : "en";
    try { window.localStorage.setItem(preferenceKey, currentLanguage); } catch { /* Session-only preference. */ }
    window.dispatchEvent(new Event(changeEvent));
  }, []);
  useEffect(() => {
    document.documentElement.lang = language;
    document.title = language === "en" ? "MediGuard | Smart Medication Platform" : "MediGuard｜智慧用藥守護平台";
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute("content", language === "en"
      ? "Manage prescriptions, explore medication information, and verify medicines with a smart capture device."
      : "整合藥單管理、藥品資訊與智慧暗箱辨識的用藥守護平台。");
  }, [language]);
  return <LanguageContext.Provider value={{ language, toggle }}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("LanguageProvider is required.");
  return value;
}

export function useTranslation() {
  const { language } = useLanguage();
  return useCallback(<T,>(value: T): T => translate(value, language), [language]);
}

export function LanguageToggle() {
  const { language, toggle } = useLanguage();
  const label = language === "en" ? "切換為繁體中文" : "Switch to English";
  return <button type="button" className="language-toggle" onClick={toggle} aria-label={label} title={label}>
    <Languages size={17} aria-hidden="true"/><span lang={language === "en" ? "zh-Hant" : "en"}>{language === "en" ? "繁體中文" : "English"}</span>
  </button>;
}
