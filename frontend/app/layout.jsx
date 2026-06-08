import "./globals.css";

export const metadata = {
  title: "AviAssess — Interview",
  description: "AviAssess pilot interview assessment (Phase 6.1 — text flow).",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
