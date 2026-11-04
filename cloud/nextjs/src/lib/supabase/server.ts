import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

export async function createSupabaseServerClient() {
  const store = await cookies();
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("Supabase environment variables not configured");
  return createServerClient(url, key, {
    cookies: {
      getAll() { return store.getAll(); },
      setAll(values) {
        try { values.forEach(({name,value,options})=>store.set(name,value,options)); }
        catch { /* Server components are read-only; Proxy refresh should update cookies. */ }
      },
    },
  });
}
