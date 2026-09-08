import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Adaptive Crypto Trading Platform",
  description: "Adaptive Crypto Trading Platform Development Environment",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "sans-serif" }}>{children}</body>
    </html>
  );
}
