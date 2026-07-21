import { notFound } from "next/navigation";
import Link from "next/link";
import { api, authApi } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";
import YouTubePlayer from "@/app/components/YouTubePlayer";

export default async function ComposerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const [composer, me] = await Promise.all([
    api.getComposer(id).catch(() => null),
    authApi.getMe().catch(() => null),
  ]);
  if (!composer) notFound();

  // 代表作（先頭ゲーム）のトラック情報を取得してプレーヤーに使う
  const featuredGame = composer.games.length > 0
    ? await api.getGame(composer.games[0].id).catch(() => null)
    : null;

  const featuredTracks = featuredGame?.tracks ?? [];
  const hasPlayer = featuredTracks.some((t) => t.youtube_video_id);

  return (
    <div className="space-y-8">
      {/* 作曲家情報 */}
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">{composer.name}</h1>
        {composer.bio && (
          <p className="max-w-2xl text-white/60 leading-relaxed">{composer.bio}</p>
        )}
      </div>

      {/* 代表作のプレーヤー：ページを開いた直後に音楽を体感 */}
      {hasPlayer && featuredGame && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-white/30">
              代表作
            </p>
            <Link
              href={`/games/${featuredGame.id}`}
              className="text-sm font-medium text-white/70 hover:text-white transition-colors"
            >
              {featuredGame.title} →
            </Link>
          </div>
          <YouTubePlayer tracks={featuredTracks} gameTitle={featuredGame.title} gameId={featuredGame.id} isLoggedIn={!!me} />
        </section>
      )}

      {/* 担当ゲーム一覧 */}
      {composer.games.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            担当タイトル
            <span className="ml-2 normal-case font-normal text-white/25">
              ({composer.games.length}件)
            </span>
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {composer.games.map((game) => (
              <GameCard key={game.id} game={game} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
