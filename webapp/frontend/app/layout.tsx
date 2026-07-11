import type { Metadata } from "next";
import "./globals.css";
import HistorySidebar from "@/components/HistorySidebar";

export const metadata: Metadata = {
  title: "인쇄판 문안검사 뷰어",
  description: "Print-plate defect detection viewer",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-page text-ink-primary antialiased">
        <div className="flex min-h-screen flex-col md:flex-row">
          <HistorySidebar />
          <div className="min-w-0 flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
