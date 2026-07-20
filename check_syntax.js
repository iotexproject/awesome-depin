const fs = require('fs');
const babel = require('@babel/core');

function checkFile(filename) {
  const content = fs.readFileSync(filename, 'utf-8');
  const scriptMatch = content.match(/<script\b(?=[^>]*\btype="text\/babel")[^>]*>([\s\S]*?)<\/script>/);

  if (scriptMatch) {
    const code = scriptMatch[1];
    try {
      babel.transformSync(code, {
        presets: ['@babel/preset-react'],
        filename: 'index.jsx'
      });
      console.log(`${filename}: Syntax is valid!`);
      return true;
    } catch (e) {
      console.error(`${filename}: Syntax Error:`, e.message);
      return false;
    }
  }

  const standardScripts = [...content.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*\btype="text\/babel")[^>]*>([\s\S]*?)<\/script>/g)];
  if (!standardScripts.length) {
    console.log(`${filename}: Could not find script`);
    return false;
  }

  try {
    for (const [idx, match] of standardScripts.entries()) {
      new Function(match[1]);
      console.log(`${filename}: Script ${idx + 1} syntax is valid!`);
    }
    return true;
  } catch (e) {
    console.error(`${filename}: Syntax Error:`, e.message);
    return false;
  }
}

const res1 = checkFile('index.html');
const res2 = checkFile('qtail-mvp-presentation.html');
const res3 = checkFile('qtail-data-engine.html');
const res4 = checkFile('qtail-openx-training.html');
const res5 = checkFile('quantum-embodied-data-service.html');

if (!res1 || !res2 || !res3 || !res4 || !res5) {
  process.exit(1);
}
