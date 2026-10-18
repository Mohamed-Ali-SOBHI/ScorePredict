// Hybrid encryption: the decryption key stays on the owner's computer.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const [action, ...rest] = process.argv.slice(2);
const args = Object.fromEntries(Array.from({length:rest.length/2},(_,i)=>[rest[2*i],rest[2*i+1]]));
const publicRoot = path.resolve(__dirname, 'static');
function privateTarget(target) {
  const absolute=path.resolve(target);
  if (absolute===publicRoot || absolute.startsWith(publicRoot+path.sep)) throw new Error('Private output cannot be written into the public website.');
  return absolute;
}
try {
  if (action==='init') {
    const privatePath=privateTarget(args['--private-key']);
    if (fs.existsSync(privatePath)) {
      const key=crypto.createPrivateKey(fs.readFileSync(privatePath));
      fs.writeFileSync(args['--public-key'],crypto.createPublicKey(key).export({type:'spki',format:'pem'}));
    } else {
      const pair=crypto.generateKeyPairSync('rsa',{modulusLength:3072,
        publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});
      fs.mkdirSync(path.dirname(privatePath),{recursive:true});
      fs.writeFileSync(privatePath,pair.privateKey,{flag:'wx',mode:0o600});
      fs.writeFileSync(args['--public-key'],pair.publicKey);
    }
    process.stdout.write('Private observation recipient configured.\n');
  } else if (action==='encrypt') {
    const recipient=fs.readFileSync(args['--public-key']);
    const key=crypto.randomBytes(32),iv=crypto.randomBytes(12);
    const cipher=crypto.createCipheriv('aes-256-gcm',key,iv);
    const encrypted=Buffer.concat([cipher.update(fs.readFileSync(args['--input'])),cipher.final()]);
    const envelope={schemaVersion:1,algorithm:'RSA-OAEP-SHA256+AES-256-GCM',
      recipient:crypto.createHash('sha256').update(crypto.createPublicKey(recipient).export({type:'spki',format:'der'})).digest('hex'),
      key:crypto.publicEncrypt({key:recipient,oaepHash:'sha256'},key).toString('base64'),
      iv:iv.toString('base64'),tag:cipher.getAuthTag().toString('base64'),data:encrypted.toString('base64')};
    fs.writeFileSync(privateTarget(args['--output']),JSON.stringify(envelope));
  } else if (action==='decrypt') {
    const envelope=JSON.parse(fs.readFileSync(args['--input'],'utf8'));
    if(envelope.schemaVersion!==1 || envelope.algorithm!=='RSA-OAEP-SHA256+AES-256-GCM') throw new Error('Unsupported encrypted report.');
    const privateKey=fs.readFileSync(args['--private-key']);
    const key=crypto.privateDecrypt({key:privateKey,oaepHash:'sha256'},Buffer.from(envelope.key,'base64'));
    const decipher=crypto.createDecipheriv('aes-256-gcm',key,Buffer.from(envelope.iv,'base64'));
    decipher.setAuthTag(Buffer.from(envelope.tag,'base64'));
    const plain=Buffer.concat([decipher.update(Buffer.from(envelope.data,'base64')),decipher.final()]);
    fs.writeFileSync(privateTarget(args['--output']),plain,{mode:0o600});
  } else throw new Error('Expected init, encrypt or decrypt.');
} catch (error) {
  process.stderr.write('Private observation encryption failed: '+error.message+'\n');
  process.exitCode=1;
}
