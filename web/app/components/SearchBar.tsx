"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, Game, Composer } from "@/app/lib/api";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [games, setGames] = useState<Game[]>([]);
  const [composers, setComposers] = useState<Composer[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false); // 検索が完了したかどうか
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (query.length < 2) {
      setGames([]);
      setComposers([]);
      setOpen(false);
      setSearched(false);
      return;
    }
    setSearched(false);
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const [g, c] = await Promise.all([
          api.searchGames(query),
          api.searchComposers(query),
        ]);
        setGames(g.slice(0, 5));
        setComposers(c.slice(0, 3));
        setSearched(true);
        setOpen(true);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const hasResults = games.length > 0 || composers.length > 0;
  const showEmpty = searched && !loading && !hasResults && query.length >= 2;

  return (
    <div ref={ref} className="relative w-full max-w-xl">
      <div className="relative">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="ゲーム名・作曲家名で検索..."
          className="w-full rounded-full border border-white/20 bg-white/10 px-5 py-3 text-sm text-white placeholder-white/50 backdrop-blur focus:border-white/40 focus:outline-none"
        />
        {loading && (
          <div className="absolute right-4 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        )}
      </div>

      {open && (hasResults || showEmpty) && (
        <div className="absolute z-50 mt-2 w-full rounded-2xl border border-white/10 bg-zinc-900 shadow-2xl overflow-hidden">
          {/* ゼロ件表示 */}
          {showEmpty && (
            <div className="px-4 py-5 text-sm text-white/40">
              <p>「{query}」に一致するゲーム・作曲家が見つかりませんでした</p>
              <p className="mt-1 text-xs">
                別のキーワードを試すか、
                <button
                  onClick={() => { setOpen(false); setQuery(""); }}
                  className="underline underline-offset-2 hover:text-white/60"
                >
                  タグで雰囲気から探す
                </button>
              </p>
            </div>
          )}

          {/* ゲーム結果 */}
          {games.length > 0 && (
            <div>
              <p className="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wider text-white/40">ゲーム</p>
              {games.map((g) => (
                <button
                  key={g.id}
                  onClick={() => { router.push(`/games/${g.id}`); setOpen(false); setQuery(""); }}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-white hover:bg-white/10"
                >
                  <span className="truncate">{g.title}</span>
                  {g.release_year && (
                    <span className="ml-auto shrink-0 text-xs text-white/40">{g.release_year}</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* 作曲家結果 */}
          {composers.length > 0 && (
            <div className={games.length > 0 ? "border-t border-white/10" : ""}>
              <p className="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wider text-white/40">作曲家</p>
              {composers.map((c) => (
                <button
                  key={c.id}
                  onClick={() => { router.push(`/composers/${c.id}`); setOpen(false); setQuery(""); }}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-white hover:bg-white/10"
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
