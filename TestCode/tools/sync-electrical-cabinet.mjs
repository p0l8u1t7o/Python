import {readFile,writeFile} from 'node:fs/promises';
for(const file of ['electrical-cabinet.js','electrical-components.js','electrical-inspector.js','electrical-inspector.css']){
  const source=await readFile(new URL('./'+file,import.meta.url));
  for(const project of ['AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly'])await writeFile(new URL('../'+project+'/web/'+(file.endsWith('.css')?'css/':'js/')+file,import.meta.url),source);
}
console.log('Updated electrical cabinet, components and inspector in five standalone websites.');
