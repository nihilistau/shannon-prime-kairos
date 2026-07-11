import numpy as np, struct, json
M=r"D:\Files\Models\Gemma4\gemma-4-12b-bucket\model.safetensors"
# my extraction
mine=np.load("var/voice/embed_audio.npz")["weight"].astype(np.float32)  # [3840,640]
print("mine shape",mine.shape,"mean|abs|",np.abs(mine).mean())
# reference decode via safetensors
try:
    from safetensors import safe_open
    with safe_open(M, framework="np") as f:
        w=f.get_tensor("model.embed_audio.embedding_projection.weight")
    w=np.asarray(w).astype(np.float32)
    print("safetensors shape",w.shape,"dtype-orig via np")
    print("max abs diff mine vs safetensors:", np.abs(mine-w).max())
except Exception as e:
    print("safetensors np failed:",e)
    try:
        from safetensors import safe_open
        with safe_open(M, framework="pt") as f:
            w=f.get_tensor("model.embed_audio.embedding_projection.weight").float().numpy()
        print("pt shape",w.shape,"max abs diff:", np.abs(mine-w).max())
    except Exception as e2:
        print("pt also failed:",e2)
