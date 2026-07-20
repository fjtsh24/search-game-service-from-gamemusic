import Link from "next/link";
import { Game } from "@/app/lib/api";

export default function GameCard({ game }: { game: Game }) {
  return (
    <Link
      href={`/games/${game.id}`}
      className="group flex flex-col rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:border-white/20 hover:bg-white/10"
    >
      <div className="mb-3 aspect-video w-full rounded-lg bg-white/5 overflow-hidden">
        {game.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={game.cover_image_url} alt={game.title} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-4xl text-white/10">♫</div>
        )}
      </div>
      <p className="text-sm font-medium text-white line-clamp-2 group-hover:text-white/90">{game.title}</p>
      {game.release_year && <p className="mt-1 text-xs text-white/40">{game.release_year}</p>}
    </Link>
  );
}
