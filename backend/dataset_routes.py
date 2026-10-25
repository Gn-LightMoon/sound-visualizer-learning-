"""音乐学院数据集浏览接口(第 8 周 C:入库模板配套,全部管理员鉴权)

入库走 CLI 脚本 backend/tools/import_dataset.py(音频文件在交付目录里,
不走 HTTP 上传);本路由只做 CMS 浏览/核对/汇报口径查询。
"""
from fastapi import APIRouter, Depends

import database
import dataset
from cms_routes import require_admin

router = APIRouter(prefix="/api/admin/dataset", tags=["音乐学院数据集"])


def _ok(data):
    return {"code": 200, "data": data}


def _fail(message: str, status_code: int = 400):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"code": status_code, "message": message})


@router.get("/summary")
def summary(operator: str = Depends(require_admin)):
    """六项计数(批次/样本/标注/录音人/同意书/错误码),每周汇报口径"""
    return _ok(dataset.dataset_summary(database.DB_PATH))


@router.get("/batches")
def batches(operator: str = Depends(require_admin)):
    """导入批次列表(倒序)"""
    return _ok(dataset.list_batches(database.DB_PATH))


@router.get("/batches/{batch_id}/samples")
def batch_samples(batch_id: str, limit: int = 200, operator: str = Depends(require_admin)):
    """某批次样本列表(不含音频二进制,文件在交付目录)"""
    return _ok(dataset.list_samples(database.DB_PATH, batch_id, limit))


@router.get("/samples/{sample_id}/annotations")
def sample_annotations(sample_id: str, operator: str = Depends(require_admin)):
    """某样本的标注行(训练标签以标注表为准)"""
    return _ok(dataset.get_annotations(database.DB_PATH, sample_id))


@router.get("/recorders")
def recorders(operator: str = Depends(require_admin)):
    """录音人登记列表"""
    return _ok(dataset.list_recorders(database.DB_PATH))
