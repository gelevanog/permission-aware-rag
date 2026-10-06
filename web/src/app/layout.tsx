import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Clearance - answers only from documents you may see",
  description: "A private company RAG: every answer comes only from documents the asking employee is allowed to read.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full text-zinc-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
