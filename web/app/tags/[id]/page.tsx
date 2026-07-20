import Link from "next/link";
import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

export default async function TagPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const [games, allTags] = await Promise.all([
    api.listGames(id, 40).catch(() => []),
    api.listTags().catch(() => []),
  ]);

  const currentTag = allTags.find((t) => t.id === id);
  const tagLabel = currentTag?.name_ja ?? currentTag?.name ?? "このタグ";
  const otherTags = allTags.filter((t) => t.id !== id);

  return (
    <div className="space-y-8">
      {/* タグ名をH1に表示 */}
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-white/30">
          雰囲気で探す
        </p>
        <h1 className="text-2xl font-bold">
          <span className="text-indigo-400">#</span> {tagLabel}
        </h1>
        {games.length > 0 && (
          <p className="mt-1 text-sm text-white/40">{games.length}件のゲーム</p>
        )}
      </div>

      {/* ゲーム一覧 / 空状態 */}
      {games.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-white/5 px-6 py-10 text-center">
          <p className="text-white/40">「{tagLabel}」のゲームはまだ登録されていません</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            <Link
              href="/"
              className="rounded-full border border-white/20 px-4 py-1.5 text-sm text-white/60 hover:border-white/40 hover:text-white transition-colors"
            >
              ← ホームへ
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {games.map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>
      )}

      {/* 他の雰囲気へのクロスナビゲーション */}
      {otherTags.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/30">
            他の雰囲気を試す
          </h2>
          <div className="flex flex-wrap gap-2">
            {otherTags.map((tag) => (
              <Link
                key={tag.id}
                href={`/tags/${tag.id}`}
                className="rounded-full border border-white/20 px-4 py-1.5 text-sm text-white/60 hover:border-indigo-400/60 hover:bg-indigo-500/10 hover:text-white transition-colors"
              >
                # {tag.name_ja ?? tag.name}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
