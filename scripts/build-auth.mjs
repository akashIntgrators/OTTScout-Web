import {build} from 'esbuild';
import {resolve} from 'node:path';
const args=process.argv.slice(2);
const emulator=args.includes('--emulator');
const outfile=resolve(args.find(value=>!value.startsWith('--'))||'account.js');
await build({entryPoints:['web/account.js'],outfile,bundle:true,define:{__OTTSCOUT_EMULATOR__:JSON.stringify(emulator)},format:'esm',target:['safari16','chrome105','firefox105'],minify:true,legalComments:'eof',logLevel:'warning'});
