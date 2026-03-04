export default {
    async fetch(request, env, ctx) {
        const ALLOWED_ORIGIN = "https://saa-ssender-sale.vercel.app";

        const origin = request.headers.get("Origin");

        // 🔒 Strict origin check
        if (origin !== ALLOWED_ORIGIN) {
            return new Response("Forbidden", { status: 403 });
        }

        // Preflight
        if (request.method === "OPTIONS") {
            return new Response(null, {
                headers: corsHeaders(ALLOWED_ORIGIN),
            });
        }

        try {
            // 🔑 Authorize with :contentReference[oaicite:0]{index=0}
            const authRes = await fetch("https://api.backblazeb2.com/b2api/v2/b2_authorize_account", {
                headers: {
                    Authorization: "Basic " + btoa(`${env.B2_KEY_ID}:${env.B2_APPLICATION_KEY}`),
                },
            });

            const auth = await authRes.json();

            const apiUrl = auth.apiUrl;
            const authToken = auth.authorizationToken;
            const downloadUrl = auth.downloadUrl;

            const url = new URL(request.url);
            const pathname = url.pathname;

            let b2Response;

            // 📤 Upload
            if (pathname === "/upload" && request.method === "POST") {
                const uploadUrlRes = await fetch(`${apiUrl}/b2api/v2/b2_get_upload_url`, {
                    method: "POST",
                    headers: {
                        Authorization: authToken,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        bucketId: env.B2_BUCKET_ID,
                    }),
                });

                const uploadData = await uploadUrlRes.json();

                const file = await request.arrayBuffer();

                // 🔒 File size limit (10MB example)
                if (file.byteLength > 10 * 1024 * 1024) {
                    return new Response("File too large", { status: 413 });
                }

                const fileName = url.searchParams.get("filename");

                b2Response = await fetch(uploadData.uploadUrl, {
                    method: "POST",
                    headers: {
                        Authorization: uploadData.authorizationToken,
                        "X-Bz-File-Name": encodeURIComponent(fileName),
                        "Content-Type": "b2/x-auto",
                        "X-Bz-Content-Sha1": "do_not_verify",
                    },
                    body: file,
                });
            }

            // 📥 Download
            else if (pathname === "/download" && request.method === "GET") {
                const fileName = url.searchParams.get("filename");

                b2Response = await fetch(
                    `${downloadUrl}/file/ssender/${fileName}`, // ✅ your bucket name used here
                    {
                        headers: {
                            Authorization: authToken,
                        },
                    }
                );
            }

            // 📄 List files
            else if (pathname === "/list") {
                b2Response = await fetch(`${apiUrl}/b2api/v2/b2_list_file_names`, {
                    method: "POST",
                    headers: {
                        Authorization: authToken,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        bucketId: env.B2_BUCKET_ID,
                        maxFileCount: 100,
                    }),
                });
            }

            // ❌ Delete
            else if (pathname === "/delete" && request.method === "POST") {
                const { fileName, fileId } = await request.json();

                b2Response = await fetch(`${apiUrl}/b2api/v2/b2_delete_file_version`, {
                    method: "POST",
                    headers: {
                        Authorization: authToken,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        fileName,
                        fileId,
                    }),
                });
            }

            else {
                return new Response("Not Found", { status: 404 });
            }

            const data = await b2Response.arrayBuffer();

            return new Response(data, {
                status: b2Response.status,
                headers: {
                    ...corsHeaders(ALLOWED_ORIGIN),
                    "Content-Type": b2Response.headers.get("Content-Type") || "application/json",
                },
            });

        } catch (err) {
            return new Response(JSON.stringify({ error: err.message }), {
                status: 500,
                headers: corsHeaders(ALLOWED_ORIGIN),
            });
        }
    },
};

function corsHeaders(origin) {
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    };
}