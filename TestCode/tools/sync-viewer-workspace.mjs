import {readFile,writeFile} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
for(const project of ['AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly']) {
  for(const [file,folder] of [['viewer-workspace.js','js'],['viewer-workspace.css','css']])
    await writeFile(new URL(project+'/web/'+folder+'/'+file,root),await readFile(new URL('tools/'+file,root)));
}
console.log('Synced viewer workspace to five projects.');
