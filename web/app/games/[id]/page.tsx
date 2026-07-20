import { notFound } from "next/navigation";
import Link from "next/link";
import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";
import YouTubePlayer from "@/app/components/YouTubePlayer";
import StarRating from "@/app/components/StarRating";

export default async function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const [game, similar] = await Promise.all([
    api.getGame(id).catch(() => null),
    api.getSimilarGames(id).catch(() => []),
  ]);

  if (!game) notFound();

  const tags = game.game_tags?.map((gt) => gt.mood_tags).filter(Boolean) ?? [];
  const composers = game.tracks
    ?.flatMap((t) => t.track_composers?.map((tc) => tc.composers) ?? [])
    .filter(Boolean)
    .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i) ?? [];

  return (
    <div className="space-y-10">

      {/* 1. YouTubeプレーヤーを最上部に（主目的を最初に） */}
      {game.tracks?.length > 0 && (
        <YouTubePlayer tracks={game.tracks} gameTitle={game.title} />
      )}

      {/* 2. ゲームメタデータ */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <div className="flex-1 space-y-4">
          <div>
            <h1 className="text-3xl font-bold leading-tight">{game.title}</h1>
            {game.title_ja && <p className="mt-1 text-white/50">{game.title_ja}</p>}
            {game.release_year && (
              <p className="mt-1 text-sm text-white/40">{game.release_year}年</p>
            )}
          </div>

          {/* タグ: # プレフィックスで「絞り込みフィルタ」であることを伝える */}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <Link
                  key={tag.id}
                  href={`/tags/${tag.id}`}
                  className="rounded-full border border-white/20 px-3 py-1 text-xs text-white/60 hover:border-indigo-400/60 hover:bg-indigo-500/10 hover:text-white transition-colors"
                >
                  # {tag.name_ja ?? tag.name}
                </Link>
              ))}
            </div>
          )}

          {/* 作曲家: ラベルを明示して「探索の起点」であることを伝える */}
          {composers.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="text-white/40 shrink-0">作曲家</span>
              {composers.map((c, i) => (
                <span key={c.id} className="flex items-center gap-1">
                  <Link
                    href={`/composers/${c.id}`}
                    className="font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
                  >
                    {c.name}
                  </Link>
                  {i < composers.length - 1 && (
                    <span className="text-white/20">·</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* 評価 + Steam */}
          <div className="flex flex-wrap items-center gap-4">
            <StarRating gameId={id} />
            {game.steam_app_id && (
              <a
                href={`https://store.steampowered.com/app/${game.steam_app_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition-colors"
              >
                Steam で見る →
              </a>
            )}
          </div>
        </div>
      </div>

      {/* 3. 類似ゲーム（件数をヘッダーで予告） */}
      {similar.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            音楽的に似たゲーム
            <span className="ml-2 normal-case font-normal text-white/25">
              ({similar.length}件)
            </span>
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
            {similar.map((g) => (
              <GameCard key={g.id} game={g} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
