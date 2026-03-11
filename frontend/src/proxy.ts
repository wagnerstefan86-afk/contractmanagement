/**
 * Next.js proxy (formerly middleware).
 * Since JWT is stored in localStorage we cannot read it here —
 * client-side AuthGuard handles session checks and redirects.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest): NextResponse {
  void request;
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
