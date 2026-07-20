import { notFound } from "next/navigation";
import { api } from "@/app/lib/api";
import GameCard from "@/app/components/GameCard";

export default async function ComposerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const composer = await api.getComposer(id).catch(() => null);
  if (!composer) notFound();

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">{composer.name}</h1>
        {composer.bio && <p className="max-w-2xl text-white/60 leading-relaxed">{composer.bio}</p>}
      </div>

      {composer.games.length > 0 && (
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-white/40">
            担当タイトル ({composer.games.length}件)
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
