import os
import json
import shutil
from pathlib import Path

def rename_fields():
    """
    批量重命名 JSON 文件中的字段：
    - chinese_phrase → phrase_cn
    - english_phrase → phrase_en
    """
    data_dir = "assets/bible_data"
    
    # 也检查大写 B 的目录
    data_dir_alt = "assets/Bible_data"
    
    # 确定使用哪个目录
    if os.path.exists(data_dir):
        target_dir = data_dir
    elif os.path.exists(data_dir_alt):
        target_dir = data_dir_alt
    else:
        print("❌ 找不到数据文件夹 (assets/bible_data 或 assets/Bible_data)")
        return
    
    if not os.path.exists(target_dir):
        print(f"❌ 找不到文件夹: {target_dir}")
        return
    
    # 创建备份目录
    backup_dir = os.path.join(target_dir, "_backup_rename")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    fixed_count = 0
    skipped_count = 0
    error_count = 0
    total_items_fixed = 0
    
    for filename in os.listdir(target_dir):
        # 跳过 blueprint 文件和备份目录
        if filename.startswith("blueprint") or filename.startswith("_backup"):
            skipped_count += 1
            continue
            
        if not filename.endswith(".json"):
            continue
            
        file_path = os.path.join(target_dir, filename)
        
        try:
            # 读取 JSON 文件
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查是否需要修正
            needs_fix = False
            items_fixed_in_file = 0
            
            # 处理每个条目
            for item in data:
                item_fixed = False
                
                # 1. chinese_phrase → phrase_cn
                if 'chinese_phrase' in item:
                    # 如果 phrase_cn 已存在，保留现有的；否则重命名
                    if 'phrase_cn' not in item:
                        item['phrase_cn'] = item.pop('chinese_phrase')
                        item_fixed = True
                    else:
                        # 如果两个都存在，删除旧的
                        item.pop('chinese_phrase')
                        item_fixed = True
                
                # 2. english_phrase → phrase_en
                if 'english_phrase' in item:
                    # 如果 phrase_en 已存在，保留现有的；否则重命名
                    if 'phrase_en' not in item:
                        item['phrase_en'] = item.pop('english_phrase')
                        item_fixed = True
                    else:
                        # 如果两个都存在，删除旧的
                        item.pop('english_phrase')
                        item_fixed = True
                
                if item_fixed:
                    needs_fix = True
                    items_fixed_in_file += 1
            
            # 如果需要修正，备份并写回文件
            if needs_fix:
                # 备份原文件
                backup_path = os.path.join(backup_dir, filename)
                shutil.copy2(file_path, backup_path)
                
                # 写回修正后的数据
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                print(f"✅ {filename}: 修正了 {items_fixed_in_file} 个条目")
                fixed_count += 1
                total_items_fixed += items_fixed_in_file
            else:
                print(f"⏭️  {filename}: 无需修正")
                skipped_count += 1
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误 ({filename}): {e}")
            error_count += 1
        except Exception as e:
            print(f"❌ 处理错误 ({filename}): {e}")
            error_count += 1
    
    # 输出统计
    print("\n" + "="*60)
    print(f"📊 处理完成:")
    print(f"   ✅ 已修正文件: {fixed_count} 个")
    print(f"   📝 修正条目总数: {total_items_fixed} 个")
    print(f"   ⏭️  已跳过文件: {skipped_count} 个")
    print(f"   ❌ 错误文件: {error_count} 个")
    if fixed_count > 0:
        print(f"\n💾 备份文件保存在: {backup_dir}")
        print(f"   如需恢复，请从备份目录复制文件回原目录")

if __name__ == "__main__":
    rename_fields()

