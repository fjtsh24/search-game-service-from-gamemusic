"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { authApi, isEstimatedTag, ScoredTag } from "@/app/lib/api";

type Props = {
  tags: ScoredTag[];
  gameId: string;
};

export default function TagsWithFlagButton({ tags, gameId }: Props) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [flagged, setFlagged] = useState<Set<string>>(new Set());

  useEffect(() => {
    authApi.getMe().then(() => setIsLoggedIn(true)).catch(() => {});
  }, []);

  const handleFlag = async (tagId: string) => {
    try {
      await authApi.flagTag(gameId, tagId);
      setFlagged((prev) => new Set(prev).add(tagId));
    } catch {
      // ネットワーク障害等は無視
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      {tags.map((tag) => {
        // 確信度の低いタグ（ゲームの雰囲気からの推定）は「推定」と明示する
        const estimated = isEstimatedTag(tag);
        return (
        <span key={tag.id} className="group relative flex items-center gap-1">
          <Link
            href={`/tags/${tag.id}`}
            title={
              estimated
                ? "ゲームの雰囲気から推定したタグです（音楽の情報から直接付与したものではありません）"
                : undefined
            }
            className={`rounded-full border px-3 py-1 text-xs transition-colors hover:border-indigo-400/60 hover:bg-indigo-500/10 hover:text-white ${
              estimated
                ? "border-dashed border-white/15 text-white/40"
                : "border-white/20 text-white/60"
            }`}
          >
            # {tag.name_ja ?? tag.name}
            {estimated && <span className="ml-1 text-[10px] text-white/30">推定</span>}
          </Link>
          {isLoggedIn && !flagged.has(tag.id) && (
            <button
              onClick={() => handleFlag(tag.id)}
              title="このタグは間違っていると思う"
              className="hidden group-hover:inline-flex items-center text-white/20 hover:text-orange-400 text-xs transition-colors"
              aria-label={`「${tag.name_ja ?? tag.name}」タグを報告`}
            >
              ⚑
            </button>
          )}
          {flagged.has(tag.id) && (
            <span className="text-xs text-orange-400/60" title="報告を受け付けました">⚑</span>
          )}
        </span>
        );
      })}
    </div>
  );
}
