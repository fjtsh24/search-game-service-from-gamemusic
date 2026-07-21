import Link from "next/link";
import { Game } from "@/app/lib/api";

type Props = {
  game: Game;
  /** カード右上などに重ねるバッジ（ライブラリの評価表示などに使用） */
  badge?: React.ReactNode;
};

export default function GameCard({ game, badge }: Props) {
  return (
    <Link
      href={`/games/${game.id}`}
      className="group flex flex-col rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:border-white/20 hover:bg-white/10"
    >
      {/* カバー画像 + ▶ オーバーレイ */}
      <div className="relative mb-3 aspect-video w-full rounded-lg bg-white/5 overflow-hidden">
        {game.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={game.cover_image_url}
            alt={game.title}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-3xl text-white/10">♫</div>
        )}

        {/* 再生ボタンオーバーレイ */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/90 shadow-lg">
            <svg
              className="ml-0.5 h-5 w-5 text-zinc-900"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.34-5.89a1.5 1.5 0 0 0 0-2.54L6.3 2.84Z" />
            </svg>
          </div>
        </div>

        {/* バッジスロット（ライブラリ評価など） */}
        {badge && (
          <div className="absolute top-2 right-2">{badge}</div>
        )}
      </div>

      <p className="text-sm font-medium text-white line-clamp-2 group-hover:text-white/90">
        {game.title}
      </p>
      {game.release_year && (
        <p className="mt-1 text-xs text-white/40">{game.release_year}年</p>
      )}
      {game.game_tags && game.game_tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {game.game_tags.slice(0, 3).map((gt) => (
            <span
              key={gt.mood_tags.id}
              className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/40"
            >
              {gt.mood_tags.name_ja ?? gt.mood_tags.name}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
