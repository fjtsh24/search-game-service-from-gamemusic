"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { authApi, User, UserGame } from "@/app/lib/api";

export default function LibraryPage() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [library, setLibrary] = useState<UserGame[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; matched: number } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

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

  if (user === undefined) {
    return <p className="text-white/40">読み込み中...</p>;
  }

  if (!user) {
    return (
      <div className="space-y-4 text-center py-16">
        <p className="text-white/60">ライブラリを見るにはログインが必要です</p>
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/auth/steam`}
          className="inline-block rounded-full bg-indigo-600 px-6 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Steam でログイン
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">マイライブラリ</h1>
          <p className="mt-1 text-sm text-white/40">
            {user.display_name ?? user.steam_id} のゲーム
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleImport}
            disabled={importing}
            className="rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {importing ? "インポート中..." : "Steam ライブラリをインポート"}
          </button>
        </div>
      </div>

      {importResult && (
        <div className="rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          インポート完了 — Steam ライブラリ {importResult.imported} 件中、
          データベースに登録済みの {importResult.matched} 件を追加しました
        </div>
      )}
      {importError && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {importError}
        </div>
      )}

      {library.length === 0 ? (
        <p className="text-white/40">
          まだゲームがありません。Steam ライブラリをインポートしてください。
        </p>
      ) : (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            登録済みゲーム ({library.length} 件)
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {library.map((ug) => (
              <Link
                key={ug.id}
                href={`/games/${ug.game_id}`}
                className="group rounded-xl border border-white/10 bg-white/5 p-3 hover:border-white/20 hover:bg-white/10"
              >
                <p className="line-clamp-2 text-sm font-medium text-white group-hover:text-indigo-300">
                  {ug.games?.title}
                </p>
                {ug.rating && (
                  <p className="mt-1 text-xs text-yellow-400">{"★".repeat(ug.rating)}</p>
                )}
                {ug.steam_playtime_minutes != null && ug.steam_playtime_minutes > 0 && (
                  <p className="mt-1 text-xs text-white/30">
                    {Math.round(ug.steam_playtime_minutes / 60)} 時間
                  </p>
                )}
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="border-t border-white/10 pt-8">
        <h2 className="mb-3 text-sm font-semibold text-white/40">アカウント管理</h2>
        <button
          onClick={handleDeleteAccount}
          className="rounded-full border border-red-500/40 px-4 py-1.5 text-sm text-red-400 hover:border-red-500 hover:text-red-300"
        >
          アカウントを削除
        </button>
      </section>
    </div>
  );
}
