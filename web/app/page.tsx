import Link from "next/link";
import { api } from "@/app/lib/api";
import FeedSection from "@/app/components/FeedSection";

export default async function Home() {
  const [games, tags] = await Promise.all([
    api.listGames(undefined, 20, true).catch(() => []),
    api.listTags().catch(() => []),
  ]);

  return (
    <div className="space-y-12">
      {/* ヒーロー：サービスの価値を動機に語りかける */}
      <section className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          あのゲームに似た<br className="sm:hidden" />音楽を探そう
        </h1>
        <p className="mt-3 text-white/50">
          好きなゲームや作曲家を検索して、音楽的に似た新しいゲームを発見できます
        </p>
      </section>

      {/* メインコンテンツ：ゲーム一覧 / パーソナライズドフィード（タグより先に表示） */}
      {games.length > 0 && <FeedSection fallbackGames={games} />}

      {/* サブ導線：タグで雰囲気から探す */}
      {tags.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            または雰囲気で探す
          </h2>
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <Link
                key={tag.id}
                href={`/tags/${tag.id}`}
                className="rounded-full border border-white/20 px-4 py-1.5 text-sm text-white/70 hover:border-indigo-400/60 hover:bg-indigo-500/10 hover:text-white transition-colors"
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
