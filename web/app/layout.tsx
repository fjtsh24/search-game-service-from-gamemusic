import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import SearchBar from "@/app/components/SearchBar";
import AuthButton from "@/app/components/AuthButton";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: "GameMusic — 音楽でゲームを探す",
  description: "好きな音楽の雰囲気からゲームを発見するサービス",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja" className={`${geist.variable} h-full`}>
      <body className="min-h-full bg-zinc-950 text-white antialiased">
        <header className="sticky top-0 z-40 border-b border-white/10 bg-zinc-950/80 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
            <Link href="/" className="shrink-0 text-lg font-bold tracking-tight text-white">
              🎵 GameMusic
            </Link>
            <div className="flex-1">
              <SearchBar />
            </div>
            <AuthButton />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
