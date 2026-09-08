import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "Adaptive Crypto Trading Platform",
  description: "Local trading operations and Phase-3 R&D dashboard",
  icons: { icon: "/icon.svg", apple: "/apple-icon.png" },
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className="font-sans antialiased">{children}</body></html>
}
