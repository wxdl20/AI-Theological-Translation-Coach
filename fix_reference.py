import os
import json
import shutil
from pathlib import Path

def fix_data_format():
    """
    修正 JSON 数据格式：
    1. 统一字段名：reference -> ref
    2. 统一 trap 格式：确保始终是数组
    3. 跳过 blueprint 文件
    4. 备份原文件
    """
    data_dir = "assets/bible_data"
    if not os.path.exists(data_dir):
        print("❌ 找不到文件夹")
        return
    
    # 创建备份目录
    backup_dir = os.path.join(data_dir, "_backup")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    fixed_count = 0
    skipped_count = 0
    error_count = 0
    
    for filename in os.listdir(data_dir):
        # 跳过 blueprint 文件和备份目录
        if filename.startswith("blueprint") or filename.startswith("_backup"):
            skipped_count += 1
            continue
            
        if not filename.endswith(".json"):
            continue
            
        file_path = os.path.join(data_dir, filename)
        
        try:
            # 读取 JSON 文件
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 备份原文件
            backup_path = os.path.join(backup_dir, filename)
            shutil.copy2(file_path, backup_path)
            
            # 检查是否需要修正
            needs_fix = False
            fixed_data = []
            
            for item in data:
                # 1. 统一字段名：reference -> ref
                if 'reference' in item and 'ref' not in item:
                    item['ref'] = item.pop('reference')
                    needs_fix = True
                
                # 2. 统一 trap 格式：确保始终是数组
                if 'trap' in item:
                    if isinstance(item['trap'], str):
                        # 字符串转数组
                        item['trap'] = [item['trap']] if item['trap'].strip() else []
                        needs_fix = True
                    elif not isinstance(item['trap'], list):
                        # 其他类型转数组
                        item['trap'] = [str(item['trap'])] if item['trap'] else []
                        needs_fix = True
                    # 过滤空字符串
                    item['trap'] = [t for t in item['trap'] if t and str(t).strip()]
                else:
                    # 如果没有 trap 字段，添加空数组
                    item['trap'] = []
                    needs_fix = True
                
                fixed_data.append(item)
            
            # 如果需要修正，写回文件
            if needs_fix:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(fixed_data, f, ensure_ascii=False, indent=2)
                print(f"✅ 已修正: {filename} (备份至 {backup_path})")
                fixed_count += 1
            else:
                # 删除不需要的备份
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                print(f"⏭️  无需修正: {filename}")
                skipped_count += 1
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析错误 ({filename}): {e}")
            error_count += 1
        except Exception as e:
            print(f"❌ 处理错误 ({filename}): {e}")
            error_count += 1
    
    # 输出统计
    print("\n" + "="*50)
    print(f"📊 处理完成:")
    print(f"   ✅ 已修正: {fixed_count} 个文件")
    print(f"   ⏭️  已跳过: {skipped_count} 个文件")
    print(f"   ❌ 错误: {error_count} 个文件")
    if fixed_count > 0:
        print(f"\n💾 备份文件保存在: {backup_dir}")

if __name__ == "__main__":
    fix_data_format()