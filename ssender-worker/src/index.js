export default {
  async fetch(request, env, ctx) {
    const origin = "*";

    const corsHeaders = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);
    const pathname = url.pathname.replace(/\/+$/, "") || "/";

    try {
      // ✅ UPDATED ENV VARIABLES
      const KEY_ID = String(env.B2_S3_KEY_ID || "").trim();
      const APP_KEY = String(env.B2_S3_APP_KEY || "").trim();
      const BUCKET_ID = String(env.B2_BUCKET_ID || "").trim();
      const BUCKET_NAME = String(env.B2_S3_BUCKET || "").trim();

      // 🔍 DEBUG endpoint
      if (pathname === "/debug") {
        return new Response(JSON.stringify({
          status: "Worker Active",
          env_set: {
            B2_S3_KEY_ID: !!KEY_ID,
            B2_S3_APP_KEY: !!APP_KEY,
            B2_BUCKET_ID: !!BUCKET_ID,
            B2_S3_BUCKET: !!BUCKET_NAME
          },
          config: {
            KEY_ID_PREVIEW: KEY_ID ? KEY_ID.substring(0, 4) + "****" : false,
            BUCKET_NAME
          },
          request: { method: request.method, pathname, url: request.url }
        }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // 🔍 TEST auth
      if (pathname === "/test-auth") {
        try {
          const auth = await b2Auth(KEY_ID, APP_KEY);
          return new Response(JSON.stringify({
            ok: true,
            bucketId: BUCKET_ID,
            auth
          }), {
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        } catch (err) {
          return new Response(JSON.stringify({
            ok: false,
            error: err.message
          }), {
            status: 401,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }
      }

      // --- 1. UPLOAD ---
      if (pathname === "/upload" && request.method === "POST") {
        const fileName = url.searchParams.get("filename");
        if (!fileName) throw new Error("Missing filename parameter");

        const auth = await b2Auth(KEY_ID, APP_KEY);

        const getUrlRes = await fetch(`${auth.apiUrl}/b2api/v2/b2_get_upload_url`, {
          method: "POST",
          headers: {
            Authorization: auth.authorizationToken,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ bucketId: BUCKET_ID })
        });

        if (!getUrlRes.ok) {
          const detail = await getUrlRes.text();
          return new Response(JSON.stringify({
            error: "B2 Upload URL failed",
            detail
          }), {
            status: 502,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }

        const { uploadUrl, authorizationToken: uploadToken } = await getUrlRes.json();

        const b2Res = await fetch(uploadUrl, {
          method: "POST",
          headers: {
            Authorization: uploadToken,
            "X-Bz-File-Name": encodeURIComponent(fileName),
            "Content-Type": request.headers.get("Content-Type") || "application/octet-stream",
            "X-Bz-Content-Sha1": "do_not_verify"
          },
          body: await request.arrayBuffer()
        });

        return new Response(await b2Res.text(), {
          status: b2Res.status,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // --- 2. DOWNLOAD ---
      if (pathname === "/download" && request.method === "GET") {
        const fileName = url.searchParams.get("filename");
        if (!fileName) throw new Error("Missing filename parameter");

        const auth = await b2Auth(KEY_ID, APP_KEY);

        const dlRes = await fetch(
          `${auth.downloadUrl}/file/${BUCKET_NAME}/${encodeURIComponent(fileName)}`,
          {
            headers: { Authorization: auth.authorizationToken }
          }
        );

        if (!dlRes.ok) {
          return new Response(JSON.stringify({
            error: "B2 Download failed",
            detail: await dlRes.text()
          }), {
            status: dlRes.status,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }

        return new Response(await dlRes.arrayBuffer(), {
          status: dlRes.status,
          headers: {
            "Access-Control-Allow-Origin": origin,
            "Content-Type": dlRes.headers.get("Content-Type") || "application/octet-stream",
            "Content-Disposition": dlRes.headers.get("Content-Disposition") || ""
          }
        });
      }

      // --- 3. LIST ---
      if (pathname === "/list" && request.method === "GET") {
        const auth = await b2Auth(KEY_ID, APP_KEY);

        const listRes = await fetch(`${auth.apiUrl}/b2api/v2/b2_list_file_names`, {
          method: "POST",
          headers: {
            Authorization: auth.authorizationToken,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            bucketId: BUCKET_ID,
            maxFileCount: 100
          })
        });

        return new Response(await listRes.text(), {
          status: listRes.status,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // --- 4. DELETE ---
      if (pathname === "/delete" && request.method === "POST") {
        const { fileName, fileId } = await request.json();
        if (!fileName || !fileId) throw new Error("Missing fileName or fileId");

        const auth = await b2Auth(KEY_ID, APP_KEY);

        const delRes = await fetch(`${auth.apiUrl}/b2api/v2/b2_delete_file_version`, {
          method: "POST",
          headers: {
            Authorization: auth.authorizationToken,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ fileName, fileId })
        });

        return new Response(await delRes.text(), {
          status: delRes.status,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      return new Response(JSON.stringify({
        error: `Not Found: ${pathname} [${request.method}]`
      }), {
        status: 404,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });

    } catch (err) {
      return new Response(JSON.stringify({
        error: err.message || "Internal Server Error",
        stack: err.stack
      }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }
  }
};

// 🔐 AUTH FUNCTION
async function b2Auth(id, key) {
  const res = await fetch("https://api.backblazeb2.com/b2api/v2/b2_authorize_account", {
    headers: {
      Authorization: "Basic " + btoa(`${id}:${key}`)
    }
  });

  if (!res.ok) {
    throw new Error(await res.text());
  }

  return res.json();
}
