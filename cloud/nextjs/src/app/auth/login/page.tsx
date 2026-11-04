"use client";
import { createBrowserClient } from "@supabase/ssr";
import { useState } from "react";
export default function Login() {
  const [error,setError] = useState("");
  async function login() {
    const url=process.env.NEXT_PUBLIC_SUPABASE_URL;
    const key=process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if(!url||!key){setError("Google sign-in has not been configured by the developer.");return;}
    const supabase=createBrowserClient(url,key);
    const result=await supabase.auth.signInWithOAuth({provider:"google",options:{redirectTo:`${window.location.origin}/auth/callback`}});
    if(result.error)setError(result.error.message);
  }
  return <main style={{maxWidth:480,margin:"12vh auto",padding:24}}><h1>Job Agent</h1><p>Sign in to your private career workspace.</p><button onClick={login}>Sign in with Google</button>{error&&<p role="alert">{error}</p>}<p>Connecting Gmail to read messages is a separate, optional authorization.</p></main>;
}
