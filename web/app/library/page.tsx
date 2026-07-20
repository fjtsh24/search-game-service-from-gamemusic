"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { authApi, User, UserGame } from "@/app/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** ライブラリ専用カード：GameCard と同じビジュアル + 評価・プレイ時間オーバーレイ */
function LibraryGameCard({ ug }: { ug: UserGame }) {
  const game = ug.games;
  const playtimeHours = ug.steam_playtime_minutes
    ? Math.round(ug.steam_playtime_minutes / 60)
    : 0;

  return (
    <Link
      href={`/games/${game.id}`}
      className="group flex flex-col rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:border-white/20 hover:bg-white/10"
    >
      <div className="relative mb-3 aspect-video w-full rounded-lg bg-white/5 overflow-hidden">
        {game.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={game.cover_image_url}
            alt={game.title}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-3xl text-white/10">♫</div>
        )}
        {/* 再生ボタンオーバーレイ */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90 shadow-lg">
            <svg className="ml-0.5 h-4 w-4 text-zinc-900" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.34-5.89a1.5 1.5 0 0 0 0-2.54L6.3 2.84Z" />
            </svg>
          </div>
        </div>
        {/* 評価バッジ */}
        {ug.rating && (
          <div className="absolute top-2 right-2 rounded-full bg-black/60 px-2 py-0.5 backdrop-blur-sm">
            <span className="text-xs text-yellow-400">{"★".repeat(ug.rating)}</span>
          </div>
        )}
      </div>
      <p className="line-clamp-2 text-sm font-medium text-white group-hover:text-white/90">
        {game.title}
      </p>
      {playtimeHours > 0 && (
        <p className="mt-1 text-xs text-white/30">{playtimeHours}時間プレイ</p>
      )}
    </Link>
  );
}

export default function LibraryPage() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [library, setLibrary] = useState<UserGame[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; matched: number } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const unratedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    authApi.getMe().then(setUser).catch(() => setUser(null));
    authApi.getLibrary().then(setLibrary).catch(() => {});
  }, []);

  const handleImport = async () => {
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await authApi.importLibrary();
      setImportResult(result);
      const updated = await authApi.getLibrary();
      setLibrary(updated);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "インポートに失敗しました";
      setImportError(msg.includes("503") ? "Steam API キーが設定されていません" : msg);
    } finally {
      setImporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!confirm("アカウントとすべてのデータを削除しますか？この操作は取り消せません。")) return;
    await authApi.deleteAccount();
    window.location.href = "/";
  };

  const scrollToUnrated = () => {
    unratedRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (user === undefined) {
    return <p className="text-white/40">読み込み中...</p>;
  }

  if (!user) {
    return (
      <div className="space-y-4 text-center py-16">
        <p className="text-white/60">ライブラリを見るにはログインが必要です</p>
        <a
          href={`${API_URL}/auth/steam`}
          className="inline-block rounded-full bg-indigo-600 px-6 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Steam でログイン
        </a>
      </div>
    );
  }

  const unrated = library.filter((ug) => ug.rating === null);
  const rated = library.filter((ug) => ug.rating !== null);

  return (
    <div className="space-y-10">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">マイライブラリ</h1>
          <p className="mt-1 text-sm text-white/40">
            {user.display_name ?? user.steam_id}
            {library.length > 0 && ` · ${library.length}件`}
          </p>
        </div>
        <button
          onClick={handleImport}
          disabled={importing}
          className="rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 transition-colors"
        >
          {importing ? "インポート中..." : "Steam ライブラリをインポート"}
        </button>
      </div>

      {/* インポート結果 */}
      {importResult && (
        <div className="rounded-2xl border border-indigo-500/20 bg-indigo-500/5 px-5 py-4 space-y-3">
          <p className="text-sm text-white/80">
            インポート完了 — Steam ライブラリ {importResult.imported} 件中、
            {importResult.matched} 件をデータベースに追加しました
          </p>
          {/* インポート後のネクストアクション */}
          <div className="flex flex-wrap gap-2">
            {unrated.length > 0 && (
              <button
                onClick={scrollToUnrated}
                className="rounded-full bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 transition-colors"
              >
                プレイ済みゲームを評価する →
              </button>
            )}
            <Link
              href="/"
              className="rounded-full border border-white/20 px-4 py-1.5 text-sm text-white/70 hover:border-white/40 hover:text-white transition-colors"
            >
              フィードを確認する →
            </Link>
          </div>
        </div>
      )}
      {importError && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-5 py-3 text-sm text-red-400">
          {importError}
        </div>
      )}

      {library.length === 0 && !importResult && (
        <div className="rounded-2xl border border-white/10 bg-white/5 px-6 py-10 text-center">
          <p className="text-white/40 mb-3">まだゲームがありません</p>
          <button
            onClick={handleImport}
            disabled={importing}
            className="rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {importing ? "インポート中..." : "Steam ライブラリをインポートする"}
          </button>
        </div>
      )}

      {/* 未評価ゲーム（評価を促す） */}
      {unrated.length > 0 && (
        <section ref={unratedRef}>
          <div className="mb-4 flex items-baseline gap-3">
            <h2 className="text-base font-semibold text-white">未評価</h2>
            <span className="text-sm text-white/40">{unrated.length}件 · 評価するとフィードの精度が上がります</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {unrated.map((ug) => (
              <LibraryGameCard key={ug.id} ug={ug} />
            ))}
          </div>
        </section>
      )}

      {/* 評価済みゲーム */}
      {rated.length > 0 && (
        <section>
          <div className="mb-4 flex items-baseline gap-3">
            <h2 className="text-base font-semibold text-white">評価済み</h2>
            <span className="text-sm text-white/40">{rated.length}件</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {rated.map((ug) => (
              <LibraryGameCard key={ug.id} ug={ug} />
            ))}
          </div>
        </section>
      )}

      {/* アカウント管理（危険な操作は最下部に分離） */}
      <section className="border-t border-white/10 pt-8">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-white/30">
          アカウント管理
        </h2>
        <button
          onClick={handleDeleteAccount}
          className="rounded-full border border-red-500/40 px-4 py-1.5 text-sm text-red-400 hover:border-red-500 hover:text-red-300 transition-colors"
        >
          アカウントを削除
        </button>
      </section>
    </div>
  );
}
