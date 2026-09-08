import { useState, type CSSProperties } from 'react';
import { ComponentIllustration } from './ComponentIllustration';
import { componentVisual } from '../componentVisuals';

interface ImageItem {
  name: string;
  photo: string | null;
  slug?: string;
  code?: string;
  name_en?: string;
  category?: string;
  photo_credit?: string;
  photo_source_url?: string;
}

/** 照片優先；缺檔或載入失敗時使用本地示意圖，不修改原始照片資料。 */
export function ComponentImage({ item, className = '', style, showCredit = false }: {
  item: ImageItem;
  className?: string;
  style?: CSSProperties;
  showCredit?: boolean;
}) {
  // 依圖片網址重建狀態：切換元件後會重新嘗試新照片。
  return <ImageContent key={JSON.stringify([item.slug, item.code, item.name, item.photo])} item={item} className={className} style={style} showCredit={showCredit} />;
}

function ImageContent({ item, className, style, showCredit }: {
  item: ImageItem;
  className: string;
  style?: CSSProperties;
  showCredit: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const [renderFailed, setRenderFailed] = useState(false);
  const visual = componentVisual(item);
  const hasPhoto = Boolean(item.photo) && !failed;
  return (
    <div className="component-image-block">
      <div className={`component-image ${className}`} style={style}>
        {hasPhoto ? (
          <img src={item.photo!} alt={item.name} loading="lazy" onError={() => setFailed(true)} />
        ) : (
          <>
            {visual && !renderFailed ? (
              <img src={visual.thumbnail} alt={`${item.name}：3D ${visual.conceptual ? '軟體概念圖' : '模型示意圖'}`} loading="lazy" decoding="async" onError={() => setRenderFailed(true)} />
            ) : <ComponentIllustration name={item.name} identity={`${item.slug ?? ''} ${item.name} ${item.name_en ?? ''}`} category={item.category ?? ''} />}
            <span className="component-image-label">{visual && !renderFailed ? (visual.conceptual ? '概念圖' : '3D 示意') : '示意圖'}</span>
          </>
        )}
      </div>
      {showCredit && hasPhoto && item.photo_credit && (
        <div className="component-image-credit">
          {item.photo_source_url ? (
            <a href={item.photo_source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>{item.photo_credit}</a>
          ) : item.photo_credit}
        </div>
      )}
    </div>
  );
}
