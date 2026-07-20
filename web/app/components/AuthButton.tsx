"use client";

import { useEffect, useState } from "react";
import { authApi, User } from "@/app/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function AuthButton() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    authApi.getMe().then(setUser).catch(() => setUser(null));
  }, []);

  // ロード中は非表示（レイアウトシフトを防ぐ）
  if (user === undefined) return <div className="w-28" />;

  if (!user) {
    return (
      <a
        href={`${API_URL}/auth/steam`}
        className="shrink-0 rounded-full bg-zinc-800 px-4 py-1.5 text-sm font-medium text-white/70 hover:bg-zinc-700 hover:text-white"
      >
        Steam でログイン
      </a>
    );
  }

  return (
    <div className="flex shrink-0 items-center gap-3">
      {user.avatar_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full" />
      )}
      <span className="max-w-[120px] truncate text-sm text-white/60">
        {user.display_name ?? user.steam_id}
      </span>
      <button
        onClick={async () => {
          await authApi.logout();
          setUser(null);
        }}
        className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-white/40 hover:bg-zinc-700 hover:text-white"
      >
        ログアウト
      </button>
    </div>
  );
}
