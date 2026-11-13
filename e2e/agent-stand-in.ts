// Stands in for the agent's service in the end-to-end tests: it records each
// claim the backend asks it to resume, and lists them at /resumed.
import { createServer } from "node:http";

const resumed: string[] = [];

createServer((request, response) => {
  const resume = /^\/api\/claims\/([^/]+)\/resume$/.exec(request.url ?? "");
  if (request.method === "POST" && resume) {
    resumed.push(resume[1]);
    response.writeHead(202).end();
  } else if (request.method === "GET" && request.url === "/resumed") {
    response
      .writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify(resumed));
  } else {
    response.writeHead(404).end();
  }
}).listen(8003, "127.0.0.1");
