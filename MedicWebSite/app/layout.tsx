import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediGuard｜智慧用藥守護平台",
  description: "整合藥單管理、藥品資訊與智慧暗箱辨識的用藥守護平台。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
