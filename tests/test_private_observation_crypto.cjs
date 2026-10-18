const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawnSync}=require('node:child_process');
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'private-report-check-'));
const script=path.resolve('production/private_observation_crypto.cjs');
const key=path.join(folder,'private.pem'),pub=path.join(folder,'public.pem');
const input=path.join(folder,'input.json'),encrypted=path.join(folder,'encrypted.json'),output=path.join(folder,'output.json');
const run=(action,args)=>spawnSync(process.execPath,[script,action,...args],{encoding:'utf8'});
try {
  assert.equal(run('init',['--private-key',key,'--public-key',pub]).status,0);
  const value=JSON.stringify({private:true,match:'PRIVATE_MATCH_TEST',signal:0.314});
  fs.writeFileSync(input,value);
  assert.equal(run('encrypt',['--input',input,'--public-key',pub,'--output',encrypted]).status,0);
  assert.equal(fs.readFileSync(encrypted,'utf8').includes('PRIVATE_MATCH_TEST'),false);
  assert.equal(run('decrypt',['--input',encrypted,'--private-key',key,'--output',output]).status,0);
  assert.equal(fs.readFileSync(output,'utf8'),value);
  const envelope=JSON.parse(fs.readFileSync(encrypted,'utf8'));
  const bytes=Buffer.from(envelope.data,'base64');bytes[0]^=1;envelope.data=bytes.toString('base64');
  fs.writeFileSync(encrypted,JSON.stringify(envelope));
  assert.notEqual(run('decrypt',['--input',encrypted,'--private-key',key,'--output',output]).status,0);
  assert.notEqual(run('encrypt',['--input',input,'--public-key',pub,'--output',path.resolve('production/static/private-test.json')]).status,0);
  process.stdout.write('Private observation: encrypted round-trip, tamper rejection, public output rejection passed.\n');
} finally {
  // Remove only known temporary files created by this test; no recursive deletion.
  for(const file of [key,pub,input,encrypted,output])if(fs.existsSync(file))fs.unlinkSync(file);
  fs.rmdirSync(folder);
}
