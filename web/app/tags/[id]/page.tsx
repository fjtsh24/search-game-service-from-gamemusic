import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

export default async function TagPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const games = await api.listGames(id, 40).catch(() => []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">タグ別ゲーム一覧</h1>
      {games.length === 0 ? (
        <p className="text-white/40">このタグのゲームはまだありません。</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {games.map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>
      )}
    </div>
  );
}
