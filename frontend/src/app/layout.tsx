import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Agent | Career Workspace",
  description: "An AI-assisted workspace for job discovery, screening and resume review.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
