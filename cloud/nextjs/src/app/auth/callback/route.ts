import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase/server";
export async function GET(request:Request) {
  const url=new URL(request.url);
  const code=url.searchParams.get("code");
  if(!code)return NextResponse.redirect(new URL("/auth/login?error=missing_code",url.origin));
  const supabase=await createSupabaseServerClient();
  const {error}=await supabase.auth.exchangeCodeForSession(code);
  if(error)return NextResponse.redirect(new URL("/auth/login?error=oauth",url.origin));
  return NextResponse.redirect(new URL("/",url.origin));
}
