import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email || !password) {
      return NextResponse.json(
        {
          error: true,
          message: "Email and password are required.",
          code: "MISSING_CREDENTIALS",
        },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });

    const data = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(
        data?.detail || {
          error: true,
          message: "Authentication failed.",
          code: "AUTH_FAILED",
        },
        { status: backendRes.status }
      );
    }

    const accessToken = data.token?.access_token;
    if (!accessToken) {
      return NextResponse.json(
        {
          error: true,
          message: "Invalid token received from auth server.",
          code: "INVALID_TOKEN_FORMAT",
        },
        { status: 500 }
      );
    }

    // Set secure httpOnly cookie
    const cookieStore = await cookies();
    cookieStore.set("admin_token", accessToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24, // 24 hours
    });

    return NextResponse.json({
      success: true,
      admin: data.admin,
    });
  } catch (error) {
    console.error("Login Proxy Error:", error);
    return NextResponse.json(
      {
        error: true,
        message: "Internal server error during login.",
        code: "INTERNAL_ERROR",
      },
      { status: 500 }
    );
  }
}
