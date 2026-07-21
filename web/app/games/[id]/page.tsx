import { notFound } from "next/navigation";
import Link from "next/link";
import { headers } from "next/headers";
import { api, GameDetail } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";
import YouTubePlayer from "@/app/components/YouTubePlayer";
import StarRating from "@/app/components/StarRating";

function pickDescription(game: GameDetail, acceptLang: string): string | null {
  const lang = acceptLang.toLowerCase();
  if (lang.startsWith("ja") && game.description_ja) return game.description_ja;
  if (lang.startsWith("zh") && game.description_zh) return game.description_zh;
  return game.description;
}

export default async function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const acceptLang = (await headers()).get("accept-language") ?? "";

  const [game, similar] = await Promise.all([
    api.getGame(id).catch(() => null),
    api.getSimilarGames(id).catch(() => []),
  ]);

  if (!game) notFound();

  const description = pickDescription(game, acceptLang);
  const tags = game.game_tags?.map((gt) => gt.mood_tags).filter(Boolean) ?? [];
  const composers = game.tracks
    ?.flatMap((t) => t.track_composers?.map((tc) => tc.composers) ?? [])
    .filter(Boolean)
    .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i) ?? [];

  return (
    <div className="space-y-10">

      {/* ヘッダー: カバー画像 + ゲーム情報 */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        {/* カバー画像 */}
        {game.cover_image_url && (
          <div className="w-full sm:w-72 shrink-0 overflow-hidden rounded-xl border border-white/10">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={game.cover_image_url}
              alt={game.title}
              className="w-full object-cover"
            />
          </div>
        )}

        <div className="flex-1 space-y-4">
          {/* タイトル・リリース年 */}
          <div>
            <h1 className="text-3xl font-bold leading-tight">{game.title}</h1>
            {game.title_ja && (
              <p className="mt-1 text-white/50">{game.title_ja}</p>
            )}
            {game.release_year && (
              <p className="mt-1 text-sm text-white/40">{game.release_year}年</p>
            )}
          </div>

          {/* 説明文 */}
          {description && (
            <p className="text-sm leading-relaxed text-white/60">{description}</p>
          )}

          {/* タグ */}
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

          {/* 作曲家 */}
          {composers.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="shrink-0 text-white/40">作曲家</span>
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

      {/* YouTubeプレーヤー */}
      {game.tracks?.length > 0 && (
        <YouTubePlayer tracks={game.tracks} gameTitle={game.title} gameId={id} />
      )}

      {/* 音楽的に似たゲーム */}
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
