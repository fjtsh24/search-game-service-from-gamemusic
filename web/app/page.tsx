import Link from "next/link";
import { api } from "@/app/lib/api";
import FeedSection from "@/app/components/FeedSection";

export default async function Home() {
  const [games, tags] = await Promise.all([
    api.listGames(undefined, 20).catch(() => []),
    api.listTags().catch(() => []),
  ]);

  return (
    <div className="space-y-12">
      <section className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          音楽の雰囲気で<br className="sm:hidden" />ゲームを探す
        </h1>
        <p className="mt-4 text-white/50">
          好きな作曲家やサウンドトラックの雰囲気から、新しいゲームを発見しよう
        </p>
      </section>

      {tags.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            雰囲気で探す
          </h2>
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <Link
                key={tag.id}
                href={`/tags/${tag.id}`}
                className="rounded-full border border-white/20 px-4 py-1.5 text-sm text-white/70 hover:border-white/40 hover:text-white transition-colors"
              >
                {tag.name_ja ?? tag.name}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* ログイン時はパーソナライズドフィード、未ログイン時はゲーム一覧 */}
      {games.length > 0 && <FeedSection fallbackGames={games} />}
    </div>
  );
}
