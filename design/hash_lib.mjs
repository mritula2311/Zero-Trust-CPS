// Canonical text hashing for verification receipts. A checkout's line-ending
// convention (CRLF on Windows with core.autocrlf=true, LF as stored in the Git
// blob) must never change a verification hash on its own -- only a real content
// change should. canonicalHash normalizes CRLF -> LF before hashing; it does not
// touch content otherwise, so a substantive source edit still changes the digest.
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';

export function canonicalize(buf) {
  return buf.toString('utf8').replace(/\r\n/g, '\n');
}

export function canonicalHash(buf) {
  return createHash('sha256').update(canonicalize(buf)).digest('hex');
}

// CLI usage: node design/hash_lib.mjs <file>  -- prints the canonical sha256 hex digest.
if (process.argv[1] && process.argv[1].replace(/\\/g, '/').endsWith('design/hash_lib.mjs')) {
  const buf = await readFile(process.argv[2]);
  console.log(canonicalHash(buf));
}
