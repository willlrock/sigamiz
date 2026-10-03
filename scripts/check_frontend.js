/* Compile browser scripts without running them or making network requests. */
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..','frontend');
let count=0;
for(const name of fs.readdirSync(root)){
 const source=fs.readFileSync(path.join(root,name),'utf8');
 if(/\.(html|js|css)$/.test(name)&&(/[\uFFFD]/.test(source)||source.includes('â€')||source.includes('ï»¿')))throw Error(`${name}: invalid text encoding`);
 if(name.endsWith('.js')){new vm.Script(source,{filename:name});count++;}
 if(name.endsWith('.html'))for(const match of source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)){
  if(/\bsrc\s*=/.test(match[1])||/application\/ld\+json/.test(match[1]))continue;
  new vm.Script(match[2],{filename:name});count++;
 }
}
console.log(`Checked ${count} browser scripts`);
