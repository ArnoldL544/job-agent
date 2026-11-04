import { NextResponse } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase/server";
export async function GET(){
  const db=await createSupabaseServerClient();
  // getUser validates with the auth server; NEVER authorize using client-supplied user_id.
  const {data:{user},error:authError}=await db.auth.getUser();
  if(authError||!user)return NextResponse.json({error:"Sign-in required"},{status:401});
  const {data,error}=await db.from("job_listings")
    .select("id,external_job_id,company,title,screening_score,screening_flags,updated_at")
    .eq("user_id",user.id).order("updated_at",{ascending:false}).limit(100);
  if(error)return NextResponse.json({error:"Unable to load jobs"},{status:500});
  return NextResponse.json({jobs:data},{headers:{"Cache-Control":"no-store"}});
}
