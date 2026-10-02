// node --import <TestCode>/core/tools/register.mjs <script>：註冊 loader.mjs（three、three/addons/、@core/）。
import { register } from 'node:module';
register('./loader.mjs', import.meta.url);
