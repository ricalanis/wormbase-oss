import "@wormbase/design/styles.css";
import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "WormBase — Institutional AI for your company's data and processes",
  description:
    "WormBase is an institutional AI agent you install into your company. Install on Monday. By Friday it has mapped your data, learned your processes, and can prove every answer with a hash.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
