import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Insure - Lead Generation & Triage",
  description: "Florida Insurance Lead Generation Command Center",
  viewport: "width=device-width, initial-scale=1, maximum-scale=1",
  icons: { icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='28' font-size='28'>🏢</text></svg>" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-white min-h-screen">{children}</body>
    </html>
  );
}
