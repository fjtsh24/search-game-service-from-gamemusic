import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

export default async function Home() {
  const games = await api.listGames(undefined, 20).catch(() => []);

  return (
    <div>
      <section className="mb-12 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          音楽の雰囲気で<br className="sm:hidden" />ゲームを探す
        </h1>
        <p className="mt-4 text-white/50">
          好きな作曲家やサウンドトラックの雰囲気から、新しいゲームを発見しよう
        </p>
      </section>

      <section>
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
          データベース収録タイトル
        </h2>
        {games.length === 0 ? (
          <p className="text-white/40">データを読み込み中...</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {games.map((game) => (
              <GameCard key={game.id} game={game} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
