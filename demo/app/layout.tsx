import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "AI Workflow Orchestrator — Live Demo",
  description:
    "Production-grade LLM orchestration: multi-step triage of tickets, emails, and system logs with fault tolerance, cost tracking, and full observability.",
  openGraph: {
    title: "AI Workflow Orchestrator — Live Demo",
    description: "Submit a real AI triage workflow and watch it execute step-by-step.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-950 text-gray-100 min-h-screen antialiased`}>
        {children}
      </body>
    </html>
  );
}
