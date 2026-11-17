// Stands in for the agent's service in the end-to-end tests: it records each
// claim the backend asks it to resume, listed at /resumed, and each dispatch or
// evaluation it is asked to start, with what it was asked, listed at /started.
import { type IncomingMessage, createServer } from "node:http";

const resumed: string[] = [];
const started: Record<string, unknown>[] = [];

async function body(
  request: IncomingMessage,
): Promise<Record<string, unknown>> {
  let text = "";
  for await (const chunk of request) text += String(chunk);
  return JSON.parse(text) as Record<string, unknown>;
}

createServer((request, response) => {
  const url = request.url ?? "";
  const resume = /^\/api\/claims\/([^/]+)\/resume$/.exec(url);
  const start = /^\/api\/(dispatches|evaluations)$/.exec(url);
  if (request.method === "POST" && resume) {
    resumed.push(resume[1]);
    response.writeHead(202).end();
  } else if (request.method === "POST" && start) {
    const kind = start[1] === "dispatches" ? "dispatch" : "evaluation";
    void body(request).then((asked) => {
      started.push({ kind, ...asked });
      response.writeHead(202).end();
    });
  } else if (request.method === "GET" && url === "/resumed") {
    response
      .writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify(resumed));
  } else if (request.method === "GET" && url === "/started") {
    response
      .writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify(started));
  } else {
    response.writeHead(404).end();
  }
}).listen(8003, "127.0.0.1");
